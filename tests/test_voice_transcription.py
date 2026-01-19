"""
Test script for voice transcription API.
Tests both transcription-only and transcription+chat endpoints.
"""
import os
import sys
import requests
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

# API base URL
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

def test_transcribe_only(audio_file_path: str, listing_id: str = None, user_id: str = None):
    """
    Test the transcription-only endpoint.
    
    Args:
        audio_file_path: Path to audio file
        listing_id: Optional listing ID
        user_id: Optional user ID
    """
    print("\n" + "="*60)
    print("TEST 1: Transcription Only")
    print("="*60)
    
    url = f"{API_BASE_URL}/api/v1/voice/transcribe"
    
    # Prepare form data
    files = {"file": open(audio_file_path, "rb")}
    data = {}
    if listing_id:
        data["listing_id"] = listing_id
    if user_id:
        data["user_id"] = user_id
    
    print(f"📤 Uploading: {audio_file_path}")
    print(f"🔗 Endpoint: {url}")
    if listing_id:
        print(f"📋 Listing ID: {listing_id}")
    
    try:
        response = requests.post(url, files=files, data=data)
        files["file"].close()
        
        print(f"📥 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Transcription successful!")
            print(f"\n📝 Transcribed Text: {result.get('text', 'N/A')}")
            if result.get('language'):
                print(f"🌐 Detected Language: {result.get('language')}")
            if result.get('duration'):
                print(f"⏱️  Duration: {result.get('duration')} seconds")
            return result
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Is the API server running?")
        print(f"   Try: uvicorn app.main:app --reload")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_transcribe_and_chat(audio_file_path: str, listing_id: str = None, user_id: str = None, conversation_id: str = None):
    """
    Test the transcription + chat endpoint.
    
    Args:
        audio_file_path: Path to audio file
        listing_id: Optional listing ID
        user_id: Optional user ID
        conversation_id: Optional conversation ID
    """
    print("\n" + "="*60)
    print("TEST 2: Transcription + Chat")
    print("="*60)
    
    url = f"{API_BASE_URL}/api/v1/voice/transcribe-and-chat"
    
    # Prepare form data
    files = {"file": open(audio_file_path, "rb")}
    data = {}
    if listing_id:
        data["listing_id"] = listing_id
    if user_id:
        data["user_id"] = user_id
    if conversation_id:
        data["conversation_id"] = conversation_id
    
    print(f"📤 Uploading: {audio_file_path}")
    print(f"🔗 Endpoint: {url}")
    if listing_id:
        print(f"📋 Listing ID: {listing_id}")
    
    try:
        response = requests.post(url, files=files, data=data)
        files["file"].close()
        
        print(f"📥 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Transcription + Chat successful!")
            
            # Show transcription
            transcription = result.get('transcription', {})
            print(f"\n📝 Transcribed Text: {transcription.get('text', 'N/A')}")
            if transcription.get('language'):
                print(f"🌐 Detected Language: {transcription.get('language')}")
            
            # Show chat response
            chat_response = result.get('chat_response', {})
            print(f"\n💬 Chat Response:")
            print(f"   Answer: {chat_response.get('answer', 'N/A')[:200]}...")
            print(f"   Conversation ID: {chat_response.get('conversation_id', 'N/A')}")
            
            return result
        else:
            print(f"❌ Error: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    
    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Is the API server running?")
        print(f"   Try: uvicorn app.main:app --reload")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_invalid_file():
    """Test with invalid file type."""
    print("\n" + "="*60)
    print("TEST 3: Invalid File Type (Error Handling)")
    print("="*60)
    
    url = f"{API_BASE_URL}/api/v1/voice/transcribe"
    
    # Create a dummy text file
    dummy_file = "test_dummy.txt"
    with open(dummy_file, "w") as f:
        f.write("This is not an audio file")
    
    files = {"file": open(dummy_file, "rb")}
    
    print(f"📤 Uploading invalid file: {dummy_file}")
    
    try:
        response = requests.post(url, files=files)
        files["file"].close()
        os.remove(dummy_file)
        
        print(f"📥 Status Code: {response.status_code}")
        
        if response.status_code == 400:
            print("✅ Error handling works correctly!")
            print(f"Response: {response.json()}")
        else:
            print(f"⚠️  Unexpected status code: {response.status_code}")
            print(f"Response: {response.text}")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        if os.path.exists(dummy_file):
            os.remove(dummy_file)


def main():
    """Main test function."""
    print("\n" + "="*60)
    print("VOICE TRANSCRIPTION API TEST SUITE")
    print("="*60)
    print(f"API Base URL: {API_BASE_URL}")
    
    # Check if audio file is provided
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
    else:
        print("\n⚠️  No audio file provided!")
        print("Usage: python tests/test_voice_transcription.py <audio_file.mp3>")
        print("\nYou can:")
        print("1. Record a test audio file")
        print("2. Download a sample audio file")
        print("3. Use an existing audio file")
        print("\nExample audio file formats: .mp3, .wav, .m4a, .mp4")
        return
    
    if not os.path.exists(audio_file):
        print(f"\n❌ Audio file not found: {audio_file}")
        return
    
    print(f"\n📁 Audio file: {audio_file}")
    file_size = os.path.getsize(audio_file)
    print(f"📊 File size: {file_size / 1024:.2f} KB")
    
    # Test parameters (optional)
    listing_id = "950b945a-5604-49a0-9cf9-3d3c16cf9c1a"  # Example listing ID
    user_id = "22c91760-ac98-4d05-b545-cdb5a7a8d23f"  # Example user ID
    
    # Run tests
    print("\n" + "="*60)
    print("RUNNING TESTS...")
    print("="*60)
    
    # Test 1: Transcription only
    result1 = test_transcribe_only(audio_file, listing_id, user_id)
    
    # Test 2: Transcription + Chat (only if transcription worked)
    if result1:
        conversation_id = None  # Will be created automatically
        test_transcribe_and_chat(audio_file, listing_id, user_id, conversation_id)
    
    # Test 3: Error handling
    test_invalid_file()
    
    print("\n" + "="*60)
    print("TEST SUITE COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()

