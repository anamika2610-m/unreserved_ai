"""
Voice transcription API endpoint using OpenAI Whisper.
Transcribes voice input and immediately deletes the file for security.
"""
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
import traceback

from app.services.rag_pipeline.llms import get_llm_client

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
async def transcribe_voice(
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
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )
        
        
        try:
            llm_client = get_llm_client()
        except ValueError as e:
            raise HTTPException(
                status_code=500,
                detail=f"OpenAI client not available: {str(e)}"
            )
        
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
            raise HTTPException(
                status_code=500,
                detail=f"Transcription failed: {str(e)}"
            )
    
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
async def transcribe_and_chat(
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
    from app.db.session import get_db
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
    db = next(get_db())
    
    try:
        # First, transcribe the audio
        transcription_result = await transcribe_voice(file)
        transcribed_text = transcription_result.text
        
        # Then, use the transcribed text in the chat endpoint
        chat_request = ChatRequest(
            question=transcribed_text,
            listing_id=safe_uuid_convert(listing_id),
            user_id=safe_uuid_convert(user_id),
            conversation_id=safe_uuid_convert(conversation_id),
        )
        
        # Call chat endpoint with transcribed text
        chat_response = await chat_message(chat_request, generator, db)
        
        return {
            "transcription": {
                "text": transcribed_text,
                "language": transcription_result.language,
                "duration": transcription_result.duration,
            },
            "conversation_id": str(chat_response.conversation_id),  # Same conversation_id for both
            "user_message": {
                "role": "user",
                "content": transcribed_text,  # Transcribed text as user message
                "conversation_id": str(chat_response.conversation_id),
            },
            "chat_response": chat_response.dict(),  # Bot response with same conversation_id
        }
    
    except Exception as e:
        print(f"❌ Chat processing failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Chat processing failed: {str(e)}"
        )
    finally:
        # Close database session
        try:
            db.close()
        except:
            pass

