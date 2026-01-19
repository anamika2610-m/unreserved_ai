"""
Real-time voice transcription API using WebSocket.
Supports streaming audio chunks and real-time transcription updates.

⚠️  STATUS: NOT CURRENTLY IN ACTIVE USE
   - This endpoint is available but not actively used in the current flow
   - Kept for future use when real-time transcription is needed
   - Currently using /api/v1/voice/transcribe-and-chat for voice input
   - To disable: Comment out voice_realtime_router in app/main.py
"""
import os
import json
import tempfile
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from typing import Optional, Dict, Any
import traceback
import base64

from app.services.rag_pipeline.llms import get_llm_client

# ------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------
router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

# Store active connections and their audio buffers
active_connections: Dict[int, Dict[str, Any]] = {}


@router.websocket("/transcribe-realtime")
async def transcribe_realtime(websocket: WebSocket):
    """
    WebSocket endpoint for real-time voice transcription.
    
    **Flow**:
    1. Client connects via WebSocket
    2. Client sends audio chunks (base64 encoded or binary)
    3. Server transcribes chunks and sends back transcription updates
    4. When client sends "finalize", server processes final transcription
    5. Optionally sends to chat endpoint and returns response
    
    **Message Format (Client → Server)**:
    - `{"type": "audio_chunk", "data": "<base64_audio>", "format": "base64"}` - Audio chunk
    - `{"type": "audio_chunk", "data": "<binary_data>", "format": "binary"}` - Binary audio chunk
    - `{"type": "finalize", "listing_id": "...", "user_id": "...", "send_to_chat": true}` - Finalize transcription
    
    **Message Format (Server → Client)**:
    - `{"type": "transcription_update", "text": "...", "is_partial": true}` - Partial transcription
    - `{"type": "transcription_final", "text": "...", "language": "en", "duration": 3.5}` - Final transcription
    - `{"type": "chat_response", "answer": "...", "conversation_id": "..."}` - Chat response (if requested)
    - `{"type": "error", "message": "..."}` - Error message
    """
    connection_id = id(websocket)
    
    try:
        # Accept WebSocket connection
        await websocket.accept()
        print(f"✅ WebSocket connection accepted: {connection_id}")
        
        # Initialize connection data
        active_connections[connection_id] = {
            "audio_chunks": [],
            "temp_file_path": None,
            "total_duration": 0.0
        }
        
        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected. Start sending audio chunks."
        })
        
        print(f"🔌 WebSocket connected: {connection_id}")
        
        while True:
            # Receive message from client
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                print(f"🔌 WebSocket disconnected: {connection_id}")
                break
            
            # Handle text messages (JSON)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")
                    
                    if msg_type == "audio_chunk":
                        # Handle audio chunk
                        await handle_audio_chunk(
                            websocket, 
                            connection_id, 
                            data
                        )
                    
                    elif msg_type == "finalize":
                        # Finalize transcription
                        await handle_finalize(
                            websocket,
                            connection_id,
                            data
                        )
                        break  # Close connection after finalization
                    
                    elif msg_type == "ping":
                        # Keep-alive ping
                        await websocket.send_json({"type": "pong"})
                    
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Unknown message type: {msg_type}"
                        })
                
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid JSON format"
                    })
            
            # Handle binary messages (raw audio data)
            elif "bytes" in message:
                # Treat binary data as audio chunk
                await handle_binary_audio_chunk(
                    websocket,
                    connection_id,
                    message["bytes"]
                )
    
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        print(traceback.format_exc())
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Server error: {str(e)}"
            })
        except:
            pass
    
    finally:
        # Cleanup
        await cleanup_connection(connection_id)


async def handle_audio_chunk(
    websocket: WebSocket,
    connection_id: int,
    data: Dict[str, Any]
):
    """Handle an audio chunk from client."""
    try:
        audio_data = data.get("data")
        format_type = data.get("format", "base64")
        
        if not audio_data:
            await websocket.send_json({
                "type": "error",
                "message": "No audio data provided"
            })
            return
        
        # Decode base64 if needed
        if format_type == "base64":
            audio_bytes = base64.b64decode(audio_data)
        else:
            audio_bytes = audio_data
        
        # Append to buffer
        conn_data = active_connections[connection_id]
        conn_data["audio_chunks"].append(audio_bytes)
        
        # Send acknowledgment
        await websocket.send_json({
            "type": "chunk_received",
            "chunks_count": len(conn_data["audio_chunks"])
        })
        
        # Optionally transcribe accumulated audio (for real-time preview)
        # This is optional - you can transcribe on finalize only
        if len(conn_data["audio_chunks"]) % 5 == 0:  # Every 5 chunks
            await transcribe_accumulated_audio(websocket, connection_id, is_partial=True)
    
    except Exception as e:
        print(f"❌ Error handling audio chunk: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Error processing audio chunk: {str(e)}"
        })


async def handle_binary_audio_chunk(
    websocket: WebSocket,
    connection_id: int,
    audio_bytes: bytes
):
    """Handle binary audio chunk."""
    try:
        # Append to buffer
        conn_data = active_connections[connection_id]
        conn_data["audio_chunks"].append(audio_bytes)
        
        # Send acknowledgment
        await websocket.send_json({
            "type": "chunk_received",
            "chunks_count": len(conn_data["audio_chunks"])
        })
        
    except Exception as e:
        print(f"❌ Error handling binary audio chunk: {e}")


async def transcribe_accumulated_audio(
    websocket: WebSocket,
    connection_id: int,
    is_partial: bool = False
):
    """Transcribe accumulated audio chunks."""
    try:
        conn_data = active_connections[connection_id]
        audio_chunks = conn_data["audio_chunks"]
        
        if not audio_chunks:
            return
        
        # Combine all chunks
        combined_audio = b"".join(audio_chunks)
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(combined_audio)
            temp_file.flush()
        
        conn_data["temp_file_path"] = temp_file_path
        
        # Transcribe using OpenAI Whisper
        llm_client = get_llm_client()
        
        with open(temp_file_path, 'rb') as audio_file:
            transcription = llm_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json"
            )
        
        # Extract transcription
        if isinstance(transcription, dict):
            transcribed_text = transcription.get('text', '')
            detected_language = transcription.get('language')
            duration = transcription.get('duration')
        else:
            transcribed_text = transcription.text if hasattr(transcription, 'text') else str(transcription)
            detected_language = getattr(transcription, 'language', None)
            duration = getattr(transcription, 'duration', None)
        
        # Send transcription update
        if is_partial:
            await websocket.send_json({
                "type": "transcription_update",
                "text": transcribed_text,
                "is_partial": True,
                "language": detected_language
            })
        else:
            await websocket.send_json({
                "type": "transcription_final",
                "text": transcribed_text,
                "language": detected_language,
                "duration": duration
            })
        
        # Cleanup temp file
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
            conn_data["temp_file_path"] = None
    
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        print(traceback.format_exc())
        await websocket.send_json({
            "type": "error",
            "message": f"Transcription failed: {str(e)}"
        })


async def handle_finalize(
    websocket: WebSocket,
    connection_id: int,
    data: Dict[str, Any]
):
    """Finalize transcription and optionally send to chat."""
    try:
        listing_id = data.get("listing_id")
        user_id = data.get("user_id")
        send_to_chat = data.get("send_to_chat", False)
        
        # Final transcription
        await transcribe_accumulated_audio(websocket, connection_id, is_partial=False)
        
        # Get final transcription text (from last message or re-transcribe)
        conn_data = active_connections[connection_id]
        audio_chunks = conn_data["audio_chunks"]
        
        if not audio_chunks:
            await websocket.send_json({
                "type": "error",
                "message": "No audio data to transcribe"
            })
            return
        
        # Combine and transcribe final version
        combined_audio = b"".join(audio_chunks)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(combined_audio)
            temp_file.flush()
        
        try:
            llm_client = get_llm_client()
            
            with open(temp_file_path, 'rb') as audio_file:
                transcription = llm_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json"
                )
            
            if isinstance(transcription, dict):
                transcribed_text = transcription.get('text', '')
                detected_language = transcription.get('language')
                duration = transcription.get('duration')
            else:
                transcribed_text = transcription.text if hasattr(transcription, 'text') else str(transcription)
                detected_language = getattr(transcription, 'language', None)
                duration = getattr(transcription, 'duration', None)
            
            # Send final transcription
            await websocket.send_json({
                "type": "transcription_final",
                "text": transcribed_text,
                "language": detected_language,
                "duration": duration
            })
            
            # Optionally send to chat endpoint
            if send_to_chat and transcribed_text:
                await send_to_chat_endpoint(
                    websocket,
                    transcribed_text,
                    listing_id,
                    user_id
                )
        
        finally:
            # Cleanup
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
    
    except Exception as e:
        print(f"❌ Finalization error: {e}")
        print(traceback.format_exc())
        await websocket.send_json({
            "type": "error",
            "message": f"Finalization failed: {str(e)}"
        })


async def send_to_chat_endpoint(
    websocket: WebSocket,
    transcribed_text: str,
    listing_id: Optional[str],
    user_id: Optional[str]
):
    """Send transcribed text to chat endpoint and return response."""
    try:
        from app.api.v1.routes.chat import ChatRequest, chat_message, get_generator
        from app.db.session import get_db
        from uuid import UUID as UUIDType
        
        # Get dependencies
        generator = get_generator()
        db = next(get_db())
        
        try:
            chat_request = ChatRequest(
                question=transcribed_text,
                listing_id=UUIDType(listing_id) if listing_id else None,
                user_id=UUIDType(user_id) if user_id else None,
                conversation_id=None,
            )
            
            chat_response = await chat_message(chat_request, generator, db)
            
            # Send chat response
            await websocket.send_json({
                "type": "chat_response",
                "answer": chat_response.answer,
                "conversation_id": str(chat_response.conversation_id),
                "timestamp": chat_response.timestamp,
                "needs_vendor_contact": chat_response.needs_vendor_contact
            })
        
        finally:
            db.close()
    
    except Exception as e:
        print(f"❌ Chat endpoint error: {e}")
        await websocket.send_json({
            "type": "error",
            "message": f"Chat processing failed: {str(e)}"
        })


async def cleanup_connection(connection_id: int):
    """Cleanup connection data and temporary files."""
    if connection_id in active_connections:
        conn_data = active_connections[connection_id]
        
        # Delete temp file if exists
        if conn_data.get("temp_file_path") and os.path.exists(conn_data["temp_file_path"]):
            try:
                os.unlink(conn_data["temp_file_path"])
                print(f"🗑️  Deleted temp file: {conn_data['temp_file_path']}")
            except:
                pass
        
        # Remove from active connections
        del active_connections[connection_id]
        print(f"🧹 Cleaned up connection: {connection_id}")

