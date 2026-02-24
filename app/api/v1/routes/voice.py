"""
Voice transcription and text-to-speech API endpoints.
- Transcribes voice input using OpenAI Whisper
- Converts text to speech using ElevenLabs TTS
"""
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root so ELEVENLABS_API_KEY is available (in case app was started from another cwd)
_project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
load_dotenv(_project_root / ".env")

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form, Query, Request

from app.core.exceptions import BadRequestError, InternalServerError, ServiceUnavailableError
from app.core.rate_limiter import rate_limit
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import UUID
import traceback
import io

import requests

from app.services.rag_pipeline.llms import get_llm_client

# ElevenLabs TTS: default voice and API base
ELEVENLABS_VOICE_ID = "56bWURjYFHyYyVf490Dp"
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

class TranscriptionResponse(BaseModel):
    """Response model for voice transcription."""
    
    text: str = Field(..., description="Transcribed text from the voice input")
    language: Optional[str] = Field(None, description="Detected language of the audio")
    duration: Optional[float] = Field(None, description="Duration of the audio in seconds")


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    response_model_exclude_none=True,
)
@rate_limit("20/minute")
async def transcribe_voice(
    request: Request,
    file: UploadFile = File(..., description="Audio file to transcribe (mp3, mp4, mpeg, mpga, m4a, wav, webm)"),
) -> TranscriptionResponse:
    """
    Transcribe voice input to text using OpenAI Whisper model.
    
    **Security**: The uploaded file is immediately deleted after transcription.
    
    **Supported formats**: mp3, mp4, mpeg, mpga, m4a, wav, webm
    
    **Usage**:
    1. Upload audio file via multipart/form-data
    2. Receive transcribed text
    3. Use transcribed text in /api/v1/chat/message endpoint
    
    **Example**:
    ```bash
    curl -X POST "http://localhost:8000/api/v1/voice/transcribe" \\
      -F "file=@audio.mp3"
    ```
    """
    temp_file_path = None
    
    try:
       
        allowed_extensions = {'.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm'}
        file_extension = os.path.splitext(file.filename or '')[1].lower()
        
        if file_extension not in allowed_extensions:
            raise BadRequestError(
                detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        
        try:
            llm_client = get_llm_client()
        except ValueError as e:
            raise InternalServerError(detail=f"OpenAI client not available: {str(e)}")
        
        # Create temporary file for audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file_path = temp_file.name
            
            # Write uploaded file to temporary file
            content = await file.read()
            temp_file.write(content)
            temp_file.flush()
        
        print(f"📝 Transcribing audio file: {file.filename} ({len(content)} bytes)")
        
        # Transcribe using OpenAI Whisper
        try:
            with open(temp_file_path, 'rb') as audio_file:
                # Use verbose_json to get additional metadata (language, duration)
                transcription = llm_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json"
                )
            
            # Extract transcription data
            # Note: verbose_json returns a dict with 'text', 'language', 'duration', etc.
            if isinstance(transcription, dict):
                transcribed_text = transcription.get('text', '')
                detected_language = transcription.get('language')
                duration = transcription.get('duration')
            else:
                # Fallback for non-verbose format
                transcribed_text = transcription.text if hasattr(transcription, 'text') else str(transcription)
                detected_language = getattr(transcription, 'language', None)
                duration = getattr(transcription, 'duration', None)
            
            print(f"✅ Transcription successful: {len(transcribed_text)} characters")
            if detected_language:
                print(f"   Detected language: {detected_language}")
            
            return TranscriptionResponse(
                text=transcribed_text,
                language=detected_language,
                duration=duration
            )
        
        except Exception as e:
            print(f"❌ Transcription failed: {e}")
            print(traceback.format_exc())
            raise InternalServerError(detail=f"Transcription failed: {str(e)}")
    
    finally:
        # SECURITY: Immediately delete the temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                print(f"🗑️  Deleted temporary file: {temp_file_path}")
            except Exception as e:
                print(f"⚠️  Warning: Could not delete temporary file {temp_file_path}: {e}")
                # Try to delete on next attempt (best effort)
                try:
                    import atexit
                    atexit.register(lambda: os.unlink(temp_file_path) if os.path.exists(temp_file_path) else None)
                except:
                    pass


@router.post(
    "/transcribe-and-chat",
    response_model=dict,
    response_model_exclude_none=True,
)
@rate_limit("20/minute")
async def transcribe_and_chat(
    request: Request,
    file: UploadFile = File(..., description="Audio file to transcribe"),
    listing_id: Optional[str] = Form(None, description="Optional listing ID"),
    user_id: Optional[str] = Form(None, description="Optional user ID"),
    conversation_id: Optional[str] = Form(None, description="Optional conversation ID"),
) -> dict:
    """
    Transcribe voice input and immediately send to chat endpoint.
    
    This is a convenience endpoint that combines transcription + chat in one call.
    The audio file is still immediately deleted after transcription.
    
    **Security**: The uploaded file is immediately deleted after transcription.
    
    **Usage**:
    ```bash
    curl -X POST "http://localhost:8000/api/v1/voice/transcribe-and-chat" \\
      -F "file=@audio.mp3" \\
      -F "listing_id=950b945a-5604-49a0-9cf9-3d3c16cf9c1a"
    ```
    """
    from app.api.v1.routes.chat import ChatRequest, chat_message, get_generator
    from app.db.connection import get_db
    from uuid import UUID as UUIDType
    
    # Helper function to safely convert string to UUID
    def safe_uuid_convert(value: Optional[str]) -> Optional[UUIDType]:
        """Convert string to UUID, handling empty strings and None."""
        if not value or value.strip() == "":
            return None
        try:
            return UUIDType(value)
        except (ValueError, TypeError):
            return None
    
    # Get dependencies
    generator = get_generator()
    
    # Use async session from connection.py
    from app.db.connection import get_session_maker
    session_maker = get_session_maker()
    
    async with session_maker() as db:
        try:
            # First, transcribe the audio
            transcription_result = await transcribe_voice(request, file)
            transcribed_text = transcription_result.text
            
            # Then, use the transcribed text in the chat endpoint
            chat_request = ChatRequest(
                question=transcribed_text,
                listing_id=safe_uuid_convert(listing_id),
                user_id=safe_uuid_convert(user_id),
                conversation_id=safe_uuid_convert(conversation_id),
            )
            
            # Call chat endpoint with transcribed text (pass Request for rate-limit context)
            chat_response = await chat_message(request, chat_request, generator, db)
            
            return {
                "transcription": {
                    "text": transcribed_text,
                    "language": transcription_result.language,
                    "duration": transcription_result.duration,
                },
                "conversation_id": str(chat_response.conversation_id),
                "user_message": {
                    "role": "user",
                    "content": transcribed_text,
                    "conversation_id": str(chat_response.conversation_id),
                },
                "chat_response": chat_response.dict(),
            }
        
        except Exception as e:
            print(f"❌ Chat processing failed: {e}")
            print(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail=f"Chat processing failed: {str(e)}"
            )


class TextToSpeechRequest(BaseModel):
    """Request model for text-to-speech (ElevenLabs)."""

    text: str = Field(
        ...,
        description="Text to convert to speech",
        min_length=1,
        max_length=5000,
    )
    speed: float = Field(
        default=1.0,
        ge=0.5,
        le=2.0,
        description="Speed of the generated speech (0.5 to 2.0)",
    )


# ElevenLabs output_format values (see https://elevenlabs.io/docs/api-reference/text-to-speech)
ELEVENLABS_OUTPUT_FORMATS = {
    "mp3": "mp3_44100_128",
    "opus": "opus_48000_64",
}

@router.post("/text-to-speech")
@rate_limit("20/minute")
async def text_to_speech(
    request: Request,
    body: TextToSpeechRequest,
    format: Literal["mp3", "opus"] = Query(
        default="mp3",
        description="Audio format for the output (mp3 or opus)",
    ),
) -> StreamingResponse:
    """
    Convert text to speech using ElevenLabs TTS.

    Uses voice ID `56bWURjYFHyYyVf490Dp`. Set `ELEVENLABS_API_KEY` in the environment.

    **Supported formats**: mp3, opus

    **Speed range**: 0.5x to 2.0x (default: 1.0x)

    **Usage**:
    ```bash
    curl -X POST "http://localhost:8000/api/v1/voice/text-to-speech?format=mp3" \\
      -H "Content-Type: application/json" \\
      -d '{"text": "Hello, this is a test."}' \\
      --output audio.mp3
    ```

    **Response**: Returns audio file as binary stream with appropriate content-type.
    """
    api_key = (
        os.getenv("ELEVENLABS_API_KEY")
        or os.getenv("XI_API_KEY")
        or os.getenv("ELEVEN_LABS_API_KEY")
    )
    if api_key:
        api_key = api_key.strip()
    if not api_key:
        raise InternalServerError(
            detail="ElevenLabs API key not configured. Set ELEVENLABS_API_KEY or XI_API_KEY in .env (in project root).",
        )

    if format not in ELEVENLABS_OUTPUT_FORMATS:
        raise BadRequestError(
            detail=f"Unsupported format. Use one of: {list(ELEVENLABS_OUTPUT_FORMATS.keys())}",
        )

    if len(body.text) > 5000:
        raise BadRequestError(detail="Text length exceeds maximum of 5000 characters")

    print(f"🔊 Converting text to speech (ElevenLabs): {len(body.text)} chars, format={format}")

    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg" if format == "mp3" else "audio/opus",
    }
    payload = {
        "text": body.text,
        "model_id": "eleven_multilingual_v2",
        "output_format": ELEVENLABS_OUTPUT_FORMATS[format],
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        audio_data = resp.content
        print(f"✅ TTS successful: {len(audio_data)} bytes generated")

        content_types = {"mp3": "audio/mpeg", "opus": "audio/opus"}
        content_type = content_types.get(format, "audio/mpeg")

        return StreamingResponse(
            io.BytesIO(audio_data),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="speech.{format}"',
                "Content-Length": str(len(audio_data)),
            },
        )
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        body = (e.response.text or str(e)) if e.response is not None else str(e)
        print(f"❌ TTS failed (HTTP {status}): {body}")
        if status >= 500:
            raise ServiceUnavailableError(detail=f"Text-to-speech failed: {body[:500]}")
        raise BadRequestError(detail=f"Text-to-speech failed: {body[:500]}")
    except Exception as e:
        print(f"❌ TTS failed: {e}")
        print(traceback.format_exc())
        raise InternalServerError(detail=f"Text-to-speech conversion failed: {str(e)}")

