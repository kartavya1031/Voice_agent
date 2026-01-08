import sys
import os
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.services.speech import create_continuous_recognizer, speak_text
from app.services.llm import ask_ai


def main():
    recognizer = create_continuous_recognizer()

    def on_recognized(evt):
        if evt.result.text:
            print(f"🧑 You said: {evt.result.text}")

            ai_reply = ask_ai(evt.result.text)
            print(f"🤖 AI says: {ai_reply}")

            # 🔊 Azure speaks directly
            speak_text(ai_reply)

    recognizer.recognized.connect(on_recognized)

    recognizer.start_continuous_recognition()
    print("🟢 AI Voice Agent Started")
    print("🎧 Listening continuously — press Ctrl + C to stop\n")

    try:
        while True:
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n👋 Stopping voice agent...")
        recognizer.stop_continuous_recognition()


if __name__ == "__main__":
    main()
