import azure.cognitiveservices.speech as speechsdk
from app.core.config import SPEECH_KEY, SPEECH_REGION

speech_config = speechsdk.SpeechConfig(
    subscription=SPEECH_KEY,
    region=SPEECH_REGION
)

speech_config.speech_recognition_language = "en-IN"
speech_config.speech_synthesis_voice_name = "en-IN-NeerjaNeural"

speech_config.set_property(
    speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
    "800"
)

speech_config.set_property(
    speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
    "800"
)

def create_continuous_recognizer():
    return speechsdk.SpeechRecognizer(speech_config=speech_config)


def speak_text(text: str):
    """
    Speak text directly using system speaker
    """
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config
    )
    synthesizer.speak_text_async(text).get()


def text_to_speech(text: str) -> bytes:
    """
    Convert text to speech and return audio bytes
    """
    # audio_config=None returns audio data directly without playing
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config,
        audio_config=None
    )
    result = synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        # Return audio bytes directly from result
        return result.audio_data
    else:
        raise Exception(f"Speech synthesis failed: {result.reason}")

def create_streaming_recognizer(on_text_callback):
    """
    Create Azure streaming STT recognizer that accepts PCM audio chunks.
    Calls on_text_callback(text) when speech is recognized.
    """

    # Push stream to feed external audio (WebSocket / Plivo)
    push_stream = speechsdk.audio.PushAudioInputStream()
    audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config
    )

    def recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            on_text_callback(evt.result.text)

    recognizer.recognized.connect(recognized)
    recognizer.start_continuous_recognition()

    return recognizer, push_stream
