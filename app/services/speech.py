import azure.cognitiveservices.speech as speechsdk
from app.core.config import SPEECH_KEY, SPEECH_REGION

# Default speech settings
DEFAULT_RECOGNITION_LANGUAGE = "en-IN"
DEFAULT_SYNTHESIS_VOICE = "en-IN-NeerjaNeural"

# Current speech settings (can be changed dynamically)
current_recognition_language = DEFAULT_RECOGNITION_LANGUAGE
current_synthesis_voice = DEFAULT_SYNTHESIS_VOICE


def get_speech_config():
    """Create a new speech config with current settings"""
    config = speechsdk.SpeechConfig(
        subscription=SPEECH_KEY,
        region=SPEECH_REGION
    )
    config.speech_recognition_language = current_recognition_language
    config.speech_synthesis_voice_name = current_synthesis_voice
    config.set_property(
        speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs,
        "400"
    )
    config.set_property(
        speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
        "400"
    )
    return config


def update_speech_settings(recognition_language: str = None, synthesis_voice: str = None):
    """Update speech settings dynamically"""
    global current_recognition_language, current_synthesis_voice
    
    if recognition_language:
        current_recognition_language = recognition_language
        print(f"🗣️ Recognition language updated to: {recognition_language}")
    
    if synthesis_voice:
        current_synthesis_voice = synthesis_voice
        print(f"🔊 Synthesis voice updated to: {synthesis_voice}")


def get_current_speech_settings():
    """Get current speech settings"""
    return {
        "recognition_language": current_recognition_language,
        "synthesis_voice": current_synthesis_voice
    }


# Legacy speech_config for backward compatibility (recreate on each use)
speech_config = get_speech_config()


def create_continuous_recognizer():
    config = get_speech_config()
    return speechsdk.SpeechRecognizer(speech_config=config)
def speak_text(text: str):
    """
    Speak text directly using system speaker
    """
    config = get_speech_config()
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=config
    )
    synthesizer.speak_text_async(text).get()
def text_to_speech(text: str) -> bytes:
    """
    Convert text to speech and return audio bytes
    """
    config = get_speech_config()
    # audio_config=None returns audio data directly without playing
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=config,
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
    config = get_speech_config()
    
    # Define audio format: 16kHz, 16-bit, mono PCM (must match client microphone settings)
    audio_format = speechsdk.audio.AudioStreamFormat(
        samples_per_second=16000,
        bits_per_sample=16,
        channels=1
    )
    # Push stream to feed external audio (WebSocket / Plivo)
    push_stream = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
    audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=config,
        audio_config=audio_config
    )
    def recognized(evt):
        print(f"✅ STT recognized: {repr(evt.result.text)}")
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            on_text_callback(evt.result.text)
    
    def recognizing(evt):
        print(f"🔄 STT recognizing (partial): {repr(evt.result.text)}")
    
    def canceled(evt):
        print(f"❌ STT canceled: {evt.result.cancellation_details.reason}")
        print(f"   Error details: {evt.result.cancellation_details.error_details}")
    
    def session_started(evt):
        print("🎙️ STT session started")
    
    def session_stopped(evt):
        print("🛑 STT session stopped")
    recognizer.recognized.connect(recognized)
    recognizer.recognizing.connect(recognizing)
    recognizer.canceled.connect(canceled)
    recognizer.session_started.connect(session_started)
    recognizer.session_stopped.connect(session_stopped)
    
    recognizer.start_continuous_recognition()
    return recognizer, push_stream
def text_to_speech_streaming(text: str):
    """
    Synthesize full audio for text, then yield in consistent-sized chunks.
    This is more reliable than real-time streaming as it prevents audio cutting.
    """
    import time
    
    config = get_speech_config()
    
    print(f"    🎤 TTS synthesizing: {text[:50]}...")
    start_time = time.time()
    
    # Set output format - Raw PCM for direct playback
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
    )
    
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=config,
        audio_config=None
    )
    
    # Wait for complete synthesis (blocking, but reliable)
    result = synthesizer.speak_text_async(text).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        audio_data = result.audio_data
        synthesis_time = time.time() - start_time
        print(f"    ✅ TTS done in {synthesis_time:.2f}s, {len(audio_data)} bytes")
        
        # Yield in larger chunks (8KB = ~250ms of audio at 16kHz/16bit)
        # Larger chunks = smoother playback
        chunk_size = 8192
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i:i + chunk_size]
    else:
        print(f"    ❌ TTS failed: {result.reason}")
        if result.cancellation_details:
            print(f"    Error: {result.cancellation_details.error_details}")
        raise Exception(f"TTS failed: {result.reason}")
def text_to_speech_sentence_streaming(llm_stream):
    """
    Stream LLM tokens and synthesize TTS sentence by sentence for low latency.
    Yields audio chunks as soon as each sentence is synthesized.
    """
    import re
    
    sentence_buffer = ""
    sentence_end_pattern = re.compile(r'[.!?]\s*')
    
    for token in llm_stream:
        sentence_buffer += token
        
        # Check for complete sentences
        match = sentence_end_pattern.search(sentence_buffer)
        if match:
            # Extract complete sentence
            end_pos = match.end()
            sentence = sentence_buffer[:end_pos].strip()
            sentence_buffer = sentence_buffer[end_pos:]
            
            if sentence:
                print(f"🔊 TTS sentence: {sentence}")
                # Stream this sentence's audio immediately
                for chunk in text_to_speech_streaming(sentence):
                    yield chunk
    
    # Handle any remaining text
    if sentence_buffer.strip():
        print(f"🔊 TTS final: {sentence_buffer.strip()}")
        for chunk in text_to_speech_streaming(sentence_buffer.strip()):
            yield chunk