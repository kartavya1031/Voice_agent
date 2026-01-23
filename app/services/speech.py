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
    
    if synthesis_voice:
        current_synthesis_voice = synthesis_voice


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
def create_streaming_recognizer(on_text_callback, on_barge_in_callback=None, sample_rate=16000):
    """
    Create Azure streaming STT recognizer that accepts PCM audio chunks.
    Calls on_text_callback(text) when speech is recognized.
    Calls on_barge_in_callback() when partial speech is detected (for barge-in).
    """
    import time
    config = get_speech_config()
    
    # Define audio format: sample_rate (default 16kHz), 16-bit, mono PCM
    audio_format = speechsdk.audio.AudioStreamFormat(
        samples_per_second=sample_rate,
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
    
    # Barge-in state tracking
    last_barge_in_time = [0]
    barge_in_debounce_ms = 300  # Minimum time between barge-in signals
    min_barge_in_words = 1  # Minimum words to trigger barge-in
    
    def recognized(evt):
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            on_text_callback(evt.result.text)
    
    def recognizing(evt):
        """
        Called when partial speech is detected.
        Trigger barge-in when user starts speaking (with debouncing).
        """
        text = evt.result.text
        if on_barge_in_callback and text:
            # Count actual words (not just any character)
            words = text.strip().split()
            if len(words) >= min_barge_in_words:
                current_time = time.time() * 1000
                # Debounce to prevent multiple triggers
                if current_time - last_barge_in_time[0] > barge_in_debounce_ms:
                    last_barge_in_time[0] = current_time
                    print(f"   🎤 User speaking: \"{text[:30]}...\"")
                    on_barge_in_callback()
    
    def canceled(evt):
        print(f"❌ STT canceled: {evt.result.cancellation_details.reason}")
    
    def session_started(evt):
        pass
    
    def session_stopped(evt):
        pass
    
    recognizer.recognized.connect(recognized)
    recognizer.recognizing.connect(recognizing)
    recognizer.canceled.connect(canceled)
    recognizer.session_started.connect(session_started)
    recognizer.session_stopped.connect(session_stopped)
    
    recognizer.start_continuous_recognition()
    return recognizer, push_stream


# =============================================================================
# TTS AUDIO CACHE - Cache synthesized audio for common phrases
# Eliminates ~200ms TTS latency for repeated phrases
# =============================================================================
_tts_cache = {}
_tts_cache_max_size = 50  # Increased cache size for more phrases

# Persistent synthesizer for connection reuse (reduces ~50-100ms per call)
_synthesizer = None
_synthesizer_voice = None


def _get_synthesizer():
    """Get or create a reusable synthesizer for the current voice."""
    global _synthesizer, _synthesizer_voice
    
    config = get_speech_config()
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
    )
    
    if _synthesizer is None or _synthesizer_voice != current_synthesis_voice:
        _synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config,
            audio_config=None
        )
        _synthesizer_voice = current_synthesis_voice
    
    return _synthesizer


def _build_ssml(text: str, voice_name: str = None) -> str:
    """
    Build SSML with prosody controls for natural-sounding speech.
    
    Features:
    - Slightly slower rate (-5%) for clarity
    - Warmer pitch (-2%) for less robotic sound
    - Natural pitch contour for human-like intonation
    - Express-as style for professional delivery
    """
    if voice_name is None:
        voice_name = current_synthesis_voice
    
    # Escape special XML characters in text
    import html
    escaped_text = html.escape(text)
    
    # Add natural pauses at punctuation
    # Replace periods, commas with appropriate breaks
    escaped_text = escaped_text.replace('. ', '. <break time="200ms"/> ')
    escaped_text = escaped_text.replace('? ', '? <break time="250ms"/> ')
    escaped_text = escaped_text.replace('! ', '! <break time="200ms"/> ')
    escaped_text = escaped_text.replace(', ', ', <break time="100ms"/> ')
    
    # Determine the language from voice name
    lang = voice_name.split('-')[0] + '-' + voice_name.split('-')[1] if '-' in voice_name else 'en-IN'
    
    # Check if voice supports express-as (most Neural voices do)
    # Use customerservice style for professional, friendly tone
    ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" 
       xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{lang}">
  <voice name="{voice_name}">
    <mstts:express-as style="customerservice" styledegree="1.0">
      <prosody rate="-3%" pitch="-1st" contour="(0%,+0Hz) (25%,+2Hz) (50%,+3Hz) (75%,+1Hz) (100%,-2Hz)">
        {escaped_text}
      </prosody>
    </mstts:express-as>
  </voice>
</speak>'''
    
    return ssml


def text_to_speech_streaming(text: str):
    """
    Synthesize full audio for text using SSML, then yield in consistent-sized chunks.
    Uses caching and connection pooling for optimal performance.
    """
    import time
    global _tts_cache
    
    # Truncate very long text
    if len(text) > 120:
        text = text[:117] + "..."
    
    # Check cache first
    cache_key = text.lower().strip()
    if cache_key in _tts_cache:
        audio_data = _tts_cache[cache_key]
        chunk_size = 2048
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i:i + chunk_size]
        return
    
    # Build SSML for natural-sounding speech
    ssml = _build_ssml(text)
    start_time = time.time()
    
    synthesizer = _get_synthesizer()
    result = synthesizer.speak_ssml_async(ssml).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        audio_data = result.audio_data
        synthesis_time = (time.time() - start_time) * 1000
        
        # Cache for future use
        if len(text) < 80 and len(_tts_cache) < _tts_cache_max_size:
            _tts_cache[cache_key] = audio_data
        
        chunk_size = 2048
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i:i + chunk_size]
    else:
        print(f"❌ TTS failed: {result.reason}")
        # Fallback: try without SSML
        result = synthesizer.speak_text_async(text).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            chunk_size = 2048
            for i in range(0, len(audio_data), chunk_size):
                yield audio_data[i:i + chunk_size]
        else:
            raise Exception(f"TTS failed: {result.reason}")


# ============================================================================
# Telephony-specific TTS (8kHz for FreJun/Teler calls)
# ============================================================================

# Telephony synthesizer cache
_telephony_synthesizer = None
_telephony_synthesizer_voice = None
_telephony_tts_cache = {}
_telephony_tts_cache_max_size = 50


def _get_telephony_synthesizer():
    """Get or create a reusable telephony synthesizer (8kHz for phone calls)"""
    global _telephony_synthesizer, _telephony_synthesizer_voice
    
    config = get_speech_config()
    # Use 8kHz 16-bit mono PCM for telephony (required by FreJun/Teler)
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw8Khz16BitMonoPcm
    )
    
    if _telephony_synthesizer is None or _telephony_synthesizer_voice != current_synthesis_voice:
        _telephony_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=config,
            audio_config=None
        )
        _telephony_synthesizer_voice = current_synthesis_voice
    
    return _telephony_synthesizer


def text_to_speech_telephony(text: str):
    """
    Synthesize audio for telephony (FreJun/Teler) at 8kHz sample rate.
    Uses SSML for natural-sounding speech.
    Yields audio chunks suitable for telephony streaming.
    """
    import time
    global _telephony_tts_cache
    
    # Truncate very long text
    if len(text) > 120:
        text = text[:117] + "..."
    
    # Check cache first
    cache_key = f"tel_{text.lower().strip()}"
    if cache_key in _telephony_tts_cache:
        audio_data = _telephony_tts_cache[cache_key]
        print(f"   📞 TTS cache hit (telephony)")
        chunk_size = 8000  # 500ms
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i:i + chunk_size]
        return
    
    # Build SSML for natural-sounding speech
    ssml = _build_ssml(text)
    start_time = time.time()
    
    synthesizer = _get_telephony_synthesizer()
    result = synthesizer.speak_ssml_async(ssml).get()
    
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        audio_data = result.audio_data
        synthesis_time = (time.time() - start_time) * 1000
        print(f"   📞 TTS (telephony): {len(audio_data)} bytes, {synthesis_time:.0f}ms")
        
        # Cache for future use
        if len(text) < 80 and len(_telephony_tts_cache) < _telephony_tts_cache_max_size:
            _telephony_tts_cache[cache_key] = audio_data
        
        chunk_size = 8000  # 500ms of audio at 8kHz 16-bit (Recommended by FreJun)
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i:i + chunk_size]
    else:
        print(f"❌ Telephony TTS failed: {result.reason}")
        # Fallback: try without SSML
        result = synthesizer.speak_text_async(text).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            chunk_size = 8000  # 500ms
            for i in range(0, len(audio_data), chunk_size):
                yield audio_data[i:i + chunk_size]
        else:
            raise Exception(f"Telephony TTS failed: {result.reason}")
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
        
        match = sentence_end_pattern.search(sentence_buffer)
        if match:
            end_pos = match.end()
            sentence = sentence_buffer[:end_pos].strip()
            sentence_buffer = sentence_buffer[end_pos:]
            
            if sentence:
                for chunk in text_to_speech_streaming(sentence):
                    yield chunk
    
    if sentence_buffer.strip():
        for chunk in text_to_speech_streaming(sentence_buffer.strip()):
            yield chunk