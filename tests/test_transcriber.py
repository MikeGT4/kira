"""Integration test for transcriber — slow, downloads ~1.5GB model on first run."""
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from kira.config import Config
from kira.transcriber import Transcriber

FIXTURES = Path(__file__).parent / "fixtures" / "samples"


@pytest.mark.integration
def test_transcribe_silence_sample_runs():
    wav_path = FIXTURES / "hello.wav"
    if not wav_path.exists():
        pytest.skip("no fixture wav")
    audio, sr = sf.read(wav_path, dtype="float32")
    assert sr == 16000
    cfg = Config()
    t = Transcriber(cfg)
    result = t.transcribe(audio)
    # We don't assert on text content because it's synthetic noise.
    # We just assert that the call completes and returns a TranscriptionResult.
    assert hasattr(result, "text")
    assert hasattr(result, "language")


def test_transcriber_constructs_without_error():
    """Pure-unit test: construct a Transcriber, don't call transcribe."""
    cfg = Config()
    t = Transcriber(cfg)
    assert t is not None
