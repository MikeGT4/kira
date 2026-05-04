"""Tests for faster-whisper transcriber. Windows-only."""
from __future__ import annotations
import sys
import numpy as np
import pytest

if sys.platform != "win32":
    pytest.skip("windows-only tests", allow_module_level=True)


@pytest.fixture
def fake_config():
    from kira.config import Config, WhisperConfig
    cfg = Config()
    cfg.whisper = WhisperConfig(model="large-v3", language="auto")
    return cfg


def test_transcriber_fw_init_lazy(monkeypatch, fake_config):
    """Instantiation should NOT load the model (lazy)."""
    from kira.transcriber_fw import Transcriber
    called = {"n": 0}

    class FakeWhisperModel:
        def __init__(self, *a, **kw):
            called["n"] += 1

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    t = Transcriber(fake_config)
    assert called["n"] == 0, "model should not load on init"


def test_transcribe_empty_audio_returns_empty(fake_config):
    from kira.transcriber_fw import Transcriber
    t = Transcriber(fake_config)
    result = t.transcribe(np.zeros(0, dtype=np.float32))
    assert result.text == ""
    assert result.language == ""


def test_transcribe_calls_model_and_joins_segments(monkeypatch, fake_config):
    from kira.transcriber_fw import Transcriber, TranscriptionResult

    class FakeInfo:
        language = "de"

    class FakeSegment:
        def __init__(self, text): self.text = text

    class FakeWhisperModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, audio, **kw):
            return iter([FakeSegment("Hallo "), FakeSegment("Welt")]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    t = Transcriber(fake_config)
    audio = np.ones(16000, dtype=np.float32) * 0.1
    result = t.transcribe(audio)
    assert result.text == "Hallo Welt"
    assert result.language == "de"


def test_transcribe_respects_explicit_language(monkeypatch, fake_config):
    from kira.transcriber_fw import Transcriber

    seen_lang = {"val": None}

    class FakeInfo:
        language = "en"

    class FakeWhisperModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, audio, **kw):
            seen_lang["val"] = kw.get("language")
            return iter([]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    fake_config.whisper.language = "en"
    t = Transcriber(fake_config)
    audio = np.ones(1600, dtype=np.float32)
    t.transcribe(audio)
    assert seen_lang["val"] == "en"


def test_transcribe_auto_language_passes_none(monkeypatch, fake_config):
    from kira.transcriber_fw import Transcriber

    seen_lang = {"val": "SENTINEL"}

    class FakeInfo:
        language = "de"

    class FakeWhisperModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, audio, **kw):
            seen_lang["val"] = kw.get("language", "SENTINEL")
            return iter([]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    fake_config.whisper.language = "auto"
    t = Transcriber(fake_config)
    audio = np.ones(1600, dtype=np.float32)
    t.transcribe(audio)
    assert seen_lang["val"] is None


def test_mlx_model_name_translated_to_faster_whisper(fake_config):
    """Mac default `mlx-community/whisper-large-v3-turbo` must become `large-v3-turbo`."""
    from kira.config import WhisperConfig
    from kira.transcriber_fw import Transcriber
    fake_config.whisper = WhisperConfig(model="mlx-community/whisper-large-v3-turbo", language="auto")
    t = Transcriber(fake_config)
    assert t._model_name == "large-v3-turbo"


def test_non_mlx_model_name_unchanged(fake_config):
    from kira.transcriber_fw import Transcriber
    t = Transcriber(fake_config)
    assert t._model_name == "large-v3"


def test_transcribe_passes_whisper_tuning_kwargs(monkeypatch, fake_config):
    """All Whisper tuning knobs must reach faster-whisper.

    Hardcoded knobs (PTT-specific, not user-tunable):
      - beam_size=1
      - vad_filter=False (Silero swallowed Mike's audio at every threshold)
      - no_speech_threshold=0.9, compression_ratio_threshold=2.0
        (the latter was 1.8 until 2026-04-28 evening — too aggressive,
        legit repetitive PTT triggered fallback into hallucinations)
      - temperature=0.0 (single value, no sweep; sweep was the second
        half of the hallucination path)
    Config-driven knobs:
      - condition_on_previous_text, initial_prompt
    """
    from kira.transcriber_fw import Transcriber

    seen: dict = {}

    class FakeInfo:
        language = "de"

    class FakeWhisperModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return iter([]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    fake_config.whisper.condition_on_previous_text = False
    fake_config.whisper.initial_prompt = "Mike Kira Ollama"
    t = Transcriber(fake_config)
    t.transcribe(np.ones(1600, dtype=np.float32))

    assert seen["beam_size"] == 1
    assert seen["vad_filter"] is False
    assert "vad_parameters" not in seen
    assert seen["no_speech_threshold"] == 0.9
    assert seen["compression_ratio_threshold"] == 2.0
    assert seen["temperature"] == 0.0
    assert seen["condition_on_previous_text"] is False
    assert seen["initial_prompt"] == "Mike Kira Ollama"


def test_known_hallucination_returns_empty_text(monkeypatch, fake_config):
    """When Whisper returns a known YouTube/subtitle boilerplate
    ('Vielen Dank.', 'Untertitel im Auftrag des ZDF', etc.), transcribe()
    must return an empty string so app.py aborts the pipeline before
    polish/inject. Mike's 2026-04-28 evening test reproduced this
    exactly: said 'test test test test' → got 'Vielen Dank.' injected."""
    from kira.transcriber_fw import Transcriber

    class FakeInfo:
        language = "de"

    class FakeSegment:
        def __init__(self, text): self.text = text

    class FakeWhisperModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, audio, **kw):
            return iter([FakeSegment("Vielen Dank.")]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    t = Transcriber(fake_config)
    result = t.transcribe(np.ones(16000, dtype=np.float32))
    assert result.text == ""
    assert result.language == "de"


def test_legitimate_speech_containing_thanks_passes_through(monkeypatch, fake_config):
    """Hallucination filter is exact-match only — Mike legitimately saying
    'Vielen Dank für deine Hilfe' must NOT be filtered (it's longer than
    every known boilerplate entry)."""
    from kira.transcriber_fw import Transcriber

    class FakeInfo:
        language = "de"

    class FakeSegment:
        def __init__(self, text): self.text = text

    class FakeWhisperModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, audio, **kw):
            return iter([FakeSegment("Vielen Dank für deine schnelle Hilfe.")]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    t = Transcriber(fake_config)
    result = t.transcribe(np.ones(16000, dtype=np.float32))
    assert "Vielen Dank für deine schnelle Hilfe" in result.text


def test_hallucination_match_is_case_insensitive(monkeypatch, fake_config):
    """Whisper sometimes returns 'VIELEN DANK.' or 'vielen dank.' depending
    on segment context — filter must catch all casings."""
    from kira.transcriber_fw import Transcriber

    class FakeInfo:
        language = "de"

    class FakeSegment:
        def __init__(self, text): self.text = text

    class FakeWhisperModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, audio, **kw):
            return iter([FakeSegment("VIELEN DANK.")]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    t = Transcriber(fake_config)
    result = t.transcribe(np.ones(16000, dtype=np.float32))
    assert result.text == ""


def test_warmup_loads_model_eagerly(monkeypatch, fake_config):
    """warmup() forces _ensure_model() so the first transcribe() doesn't pay
    the ~5 s CUDA cold-start cost. Without this, kira.log shows a multi-
    second gap between 'Loading faster-whisper model' and 'Processing audio'
    on every first F8 after launch."""
    from kira.transcriber_fw import Transcriber

    load_count = {"n": 0}

    class FakeWhisperModel:
        def __init__(self, *a, **kw):
            load_count["n"] += 1

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FakeWhisperModel)
    t = Transcriber(fake_config)
    assert load_count["n"] == 0, "construction must stay lazy"
    t.warmup()
    assert load_count["n"] == 1, "warmup must trigger model load"
    t.warmup()
    assert load_count["n"] == 1, "second warmup must reuse cached model"


def test_warmup_swallows_exceptions(monkeypatch, fake_config):
    """warmup() runs on a daemon thread at boot — it MUST NOT raise. CUDA
    OOM, missing model files, GPU driver mid-restart all need to log and
    return so Kira keeps starting."""
    from kira.transcriber_fw import Transcriber

    class FailingWhisperModel:
        def __init__(self, *a, **kw):
            raise RuntimeError("simulated CUDA OOM during boot")

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", FailingWhisperModel)
    t = Transcriber(fake_config)
    t.warmup()  # must not raise


def test_ensure_model_is_thread_safe(monkeypatch, fake_config):
    """Concurrent calls to transcribe() must construct WhisperModel exactly once."""
    import threading
    from kira.transcriber_fw import Transcriber

    call_count = {"n": 0}
    # Barrier only synchronizes the 3 worker threads so they all enter
    # transcribe() at the same instant — maximising the race window.
    # __init__ is NOT a barrier participant: with the lock in place only one
    # thread ever reaches __init__, so Barrier(4) would deadlock.
    barrier = threading.Barrier(3)

    class FakeInfo:
        language = "de"

    class SlowFakeWhisperModel:
        def __init__(self, *a, **kw):
            # Simulate slow CUDA init
            import time
            time.sleep(0.05)
            call_count["n"] += 1

        def transcribe(self, audio, **kw):
            return iter([]), FakeInfo()

    monkeypatch.setattr("kira.transcriber_fw.WhisperModel", SlowFakeWhisperModel)
    t = Transcriber(fake_config)
    audio = np.ones(1600, dtype=np.float32)

    def worker():
        # All 3 threads arrive here together, then race into _ensure_model
        barrier.wait(timeout=5)
        t.transcribe(audio)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10)

    assert call_count["n"] == 1, f"WhisperModel constructed {call_count['n']} times, expected 1"
