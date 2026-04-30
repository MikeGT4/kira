import numpy as np
import pytest

from kira.recorder import Recorder


def test_recorder_construction():
    r = Recorder()
    assert not r.is_recording


def test_stop_without_start_returns_empty():
    r = Recorder()
    audio = r.stop()
    assert audio.size == 0


def test_set_level_callback_is_stored():
    r = Recorder()
    captured = []
    r.set_level_callback(lambda x: captured.append(x))
    assert r._on_level is not None


def test_default_gain_preserves_samples():
    r = Recorder()
    r._recording = True  # bypass preroll path so _buffer captures the frame
    samples = np.array([[0.01], [-0.02], [0.05]], dtype=np.float32)
    r._callback(samples, 3, None, None)
    stored = r._buffer[0]
    np.testing.assert_allclose(stored, samples)


def test_gain_multiplies_samples():
    r = Recorder(input_gain=10.0)
    r._recording = True
    samples = np.array([[0.01], [-0.02], [0.05]], dtype=np.float32)
    r._callback(samples, 3, None, None)
    stored = r._buffer[0]
    np.testing.assert_allclose(stored, samples * 10.0, rtol=1e-5)


def test_gain_clips_when_overshooting():
    r = Recorder(input_gain=100.0)
    r._recording = True
    samples = np.array([[0.02], [-0.05], [0.5]], dtype=np.float32)
    r._callback(samples, 3, None, None)
    stored = r._buffer[0]
    assert stored.max() <= 1.0
    assert stored.min() >= -1.0
    assert stored[0, 0] == np.float32(2.0).clip(-1.0, 1.0)
    assert stored[2, 0] == 1.0


def test_callback_fills_preroll_when_not_recording():
    r = Recorder()
    # default state: _recording = False
    samples = np.array([[0.1], [0.2], [0.3]], dtype=np.float32)
    r._callback(samples, 3, None, None)
    assert len(r._buffer) == 0
    assert len(r._preroll) == 1
    assert r._preroll_samples == 3


def test_preroll_is_trimmed_to_max_size():
    """The preroll deque must not grow beyond PREROLL_SAMPLES."""
    from kira.recorder import PREROLL_SAMPLES
    r = Recorder()
    # Push more than the cap in 1000-sample chunks.
    chunk = np.zeros((1000, 1), dtype=np.float32)
    total_pushed = 0
    while total_pushed < PREROLL_SAMPLES * 2:
        r._callback(chunk, 1000, None, None)
        total_pushed += 1000
    assert r._preroll_samples <= PREROLL_SAMPLES + 1000  # at most one chunk over
    assert r._preroll_samples >= PREROLL_SAMPLES - 1000


def test_start_prepends_preroll_to_recording_buffer(monkeypatch):
    r = Recorder()
    # Seed the preroll with a known frame.
    seed = np.full((100, 1), 0.4, dtype=np.float32)
    r._callback(seed, 100, None, None)
    assert len(r._preroll) == 1

    # Stop the real stream-open from running; we only test the buffer setup.
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _NoOpStream())
    r.start()
    assert r._recording is True
    assert len(r._preroll) == 0
    assert len(r._buffer) == 1
    np.testing.assert_allclose(r._buffer[0], seed)


class _NoOpStream:
    def start(self): pass
    def stop(self): pass
    def close(self): pass


def test_level_callback_receives_boosted_rms():
    r = Recorder(input_gain=50.0)
    captured: list[float] = []
    r.set_level_callback(lambda x: captured.append(x))
    samples = np.full((100, 1), 0.01, dtype=np.float32)
    r._callback(samples, 100, None, None)
    assert len(captured) == 1
    # gain-boosted RMS should be ~0.5 (0.01 * 50)
    assert 0.49 < captured[0] < 0.51


def test_prewarm_opens_stream_once(monkeypatch):
    """prewarm() must construct + start the stream exactly once even if
    called multiple times (idempotent)."""
    constructed: list[_NoOpStream] = []

    def _factory(**kw):
        s = _NoOpStream()
        constructed.append(s)
        return s

    monkeypatch.setattr("kira.recorder.sd.InputStream", _factory)
    r = Recorder()
    r.prewarm()
    r.prewarm()  # second call must be a no-op
    assert len(constructed) == 1
    assert r._stream is constructed[0]


def test_close_clears_stream_reference(monkeypatch):
    """close() must release the stream reference under lock so a
    concurrent _callback can't race with the teardown."""
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _NoOpStream())
    r = Recorder()
    r.prewarm()
    assert r._stream is not None
    r.close()
    assert r._stream is None


def test_start_after_prewarm_does_not_open_second_stream(monkeypatch):
    """If prewarm() ran, start() must NOT lazy-open a second stream —
    the original stream is the one filling the pre-roll buffer."""
    constructed: list[_NoOpStream] = []
    monkeypatch.setattr(
        "kira.recorder.sd.InputStream",
        lambda **kw: (lambda s: constructed.append(s) or s)(_NoOpStream()),
    )
    r = Recorder()
    r.prewarm()
    r.start()
    assert len(constructed) == 1


def test_constructor_with_missing_device_does_not_raise(monkeypatch):
    """Recorder init must tolerate a configured device that isn't currently
    enumerated (e.g. USB headset switched off at boot). Was the trigger for
    the morning-of-2026-04-30 crash loop."""
    fake_devices = [
        {"name": "Realtek HD Audio", "max_input_channels": 2},
        {"name": "Mikrofon (Andere)", "max_input_channels": 1},
    ]
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: fake_devices)
    r = Recorder(input_device="ROG Theta")
    assert r._device_spec == "ROG Theta"
    assert r._input_device is None
    assert r._stream is None


def test_resolve_device_returns_none_on_miss(monkeypatch):
    """The substring miss path must return None instead of raising
    ValueError — callers decide what to do (defer, retry, or raise
    DeviceUnavailable)."""
    fake_devices = [{"name": "Realtek HD Audio", "max_input_channels": 2}]
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: fake_devices)
    r = Recorder(input_device="ROG Theta")
    assert r._resolve_device() is None


def test_resolve_device_logs_available_inputs_on_miss(monkeypatch, caplog):
    """On miss, the warning must include the configured spec and the list
    of currently-available inputs so kira.log shows what PortAudio sees."""
    import logging
    fake_devices = [
        {"name": "Realtek HD Audio", "max_input_channels": 2},
        {"name": "Output Only", "max_input_channels": 0},  # output-only filtered
    ]
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: fake_devices)
    with caplog.at_level(logging.WARNING, logger="kira.recorder"):
        r = Recorder(input_device="ROG Theta")
        r._resolve_device()
    msg = caplog.text
    assert "ROG Theta" in msg
    assert "Realtek HD Audio" in msg
    assert "Output Only" not in msg  # output-only must not be listed


def test_prewarm_with_missing_device_is_noop(monkeypatch):
    """prewarm() must NOT open a stream when the configured device is
    absent — and must NOT raise. The next start() retries the resolve."""
    fake_devices = [{"name": "Realtek HD Audio", "max_input_channels": 2}]
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: fake_devices)
    constructed: list[_NoOpStream] = []
    monkeypatch.setattr(
        "kira.recorder.sd.InputStream",
        lambda **kw: (lambda s: constructed.append(s) or s)(_NoOpStream()),
    )
    r = Recorder(input_device="ROG Theta")
    r.prewarm()  # darf nicht werfen
    assert r._stream is None
    assert len(constructed) == 0


def test_prewarm_with_present_device_opens_stream(monkeypatch):
    """Sanity: prewarm() öffnet den Stream wenn das Device da ist —
    der Happy-Path bleibt unverändert."""
    fake_devices = [
        {"name": "Mikrofon (ROG Theta Ultimate 7.)", "max_input_channels": 1},
    ]
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: fake_devices)
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _NoOpStream())
    r = Recorder(input_device="ROG Theta")
    r.prewarm()
    assert r._stream is not None
    assert r._input_device == 0


def test_prewarm_with_no_device_spec_uses_system_default(monkeypatch):
    """When no device is configured (None spec), prewarm opens the stream
    against device=None (system default) — must NOT no-op. Schützt vor
    Refactors die die _device_spec-Guard versehentlich entfernen."""
    captured: dict = {}

    def _factory(**kw):
        captured.update(kw)
        return _NoOpStream()

    monkeypatch.setattr("kira.recorder.sd.InputStream", _factory)
    r = Recorder()  # _device_spec=None
    r.prewarm()
    assert r._stream is not None
    assert captured["device"] is None


def test_start_with_missing_device_raises_device_unavailable(monkeypatch):
    """start() ohne offenen Stream + Device immer noch absent →
    DeviceUnavailable. Recording-Flag muss zurückgesetzt sein, damit
    die State-Machine nicht hängenbleibt."""
    from kira.recorder import DeviceUnavailable
    fake_devices = [{"name": "Realtek HD Audio", "max_input_channels": 2}]
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: fake_devices)
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _NoOpStream())
    r = Recorder(input_device="ROG Theta")
    r.prewarm()  # Miss, deferred
    assert r._stream is None
    with pytest.raises(DeviceUnavailable) as exc_info:
        r.start()
    assert "ROG Theta" in str(exc_info.value)
    assert r._recording is False  # Flag zurückgesetzt


def test_start_resolves_device_after_arrival(monkeypatch):
    """Mikro war bei prewarm() noch nicht da, beim ersten start() aber
    schon — Stream muss dann öffnen und Aufnahme normal laufen."""
    state = {"devices": [{"name": "Realtek HD Audio", "max_input_channels": 2}]}
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: state["devices"])
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _NoOpStream())
    r = Recorder(input_device="ROG Theta")
    r.prewarm()
    assert r._stream is None  # Miss

    # Mikro wird zwischen prewarm() und start() eingeschaltet
    state["devices"] = [
        {"name": "Mikrofon (ROG Theta Ultimate 7.)", "max_input_channels": 1},
    ]
    r.start()
    assert r._stream is not None
    assert r._recording is True
    assert r._input_device == 0
