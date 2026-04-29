import numpy as np

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
