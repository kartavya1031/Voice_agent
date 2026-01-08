# IMPORTANT: this allows running the script directly
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.speech import speech_to_text

if __name__ == "__main__":
    text = speech_to_text()
    print("📝 You said:", text)
