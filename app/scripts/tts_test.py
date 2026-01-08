import sys
import os

# Fix imports for beginner setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.speech import text_to_speech

if __name__ == "__main__":
    text = "Hello, I am your AI voice assistant."
    audio = text_to_speech(text)

    with open("tts_output.wav", "wb") as f:
        f.write(audio)

    print("🔊 Audio saved as tts_output.wav")
