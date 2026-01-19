#!/bin/bash
# Quick test script for voice transcription

echo "🎤 Voice Transcription Quick Test"
echo "=================================="
echo ""

# Check if API is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ API server is not running!"
    echo "   Start it with: uvicorn app.main:app --reload"
    exit 1
fi

echo "✅ API server is running"
echo ""

# Check if audio file is provided
if [ -z "$1" ]; then
    echo "⚠️  No audio file provided!"
    echo ""
    echo "Usage: ./quick_test_voice.sh <audio_file>"
    echo ""
    echo "Example:"
    echo "  ./quick_test_voice.sh test_audio.mp3"
    echo ""
    echo "Or test via Swagger UI:"
    echo "  http://localhost:8000/docs"
    exit 1
fi

AUDIO_FILE="$1"

if [ ! -f "$AUDIO_FILE" ]; then
    echo "❌ Audio file not found: $AUDIO_FILE"
    exit 1
fi

echo "📁 Testing with: $AUDIO_FILE"
echo ""

# Test transcription
echo "📤 Sending transcription request..."
RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/voice/transcribe" \
  -F "file=@$AUDIO_FILE")

# Check if successful
if echo "$RESPONSE" | grep -q '"text"'; then
    echo "✅ Transcription successful!"
    echo ""
    echo "📝 Transcribed Text:"
    echo "$RESPONSE" | python3 -m json.tool | grep -A 1 '"text"' | tail -1 | sed 's/.*"text": "\(.*\)".*/\1/'
    echo ""
    echo "Full Response:"
    echo "$RESPONSE" | python3 -m json.tool
else
    echo "❌ Transcription failed!"
    echo "Response: $RESPONSE"
    exit 1
fi
