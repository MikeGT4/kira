import numpy as np
import pytest

from kira.recorder import Recorder, DeviceUnavailable


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
    # active=True so der Hot-Unplug-Health-Check den Stream nicht fälschlich
    # cycelt — ohne diese Property fiel _cycle_stream_if_unhealthy() in den
    # try/except-Pfad ("active=False") und schloss den Mock-Stream noch
    # bevor start() den Recording-Flag setzen konnte.
    active = True
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


def test_start_does_not_set_recording_when_input_stream_raises(monkeypatch):
    """TOCTOU-Schutz: Wenn sd.InputStream(...) zwischen query_devices()
    und Stream-Open eine Exception wirft (z.B. weil das Device just
    weggegangen ist), darf _recording NICHT auf True bleiben — sonst
    hängt die State-Machine in RECORDING ohne tatsächlich aufzunehmen."""
    fake_devices = [
        {"name": "Mikrofon (ROG Theta Ultimate 7.)", "max_input_channels": 1},
    ]
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: fake_devices)

    def _explode(**kw):
        raise OSError("Device disappeared between resolve and open")

    monkeypatch.setattr("kira.recorder.sd.InputStream", _explode)
    r = Recorder(input_device="ROG Theta")
    with pytest.raises(OSError):
        r.start()
    assert r._recording is False
    assert r._stream is None


def test_resolve_device_returns_none_when_query_devices_raises(monkeypatch):
    """sd.query_devices() can throw PortAudioError if the Windows audio
    service crashed, was restarted, or a device is mid-disconnect during
    a USB hot-plug race. Resolve must treat this as 'not currently
    available' and return None — otherwise the exception propagates
    through prewarm()/start() and lands in the hotkey thread without
    being caught as DeviceUnavailable."""
    def _bad_query():
        raise RuntimeError("PortAudio enumeration failed")
    monkeypatch.setattr("kira.recorder.sd.query_devices", _bad_query)
    r = Recorder(input_device="ROG Theta")
    assert r._resolve_device() is None


def test_start_raises_device_unavailable_when_query_devices_raises(monkeypatch):
    """Integration: PortAudio failure during enumeration must surface
    as DeviceUnavailable from start(), not as a raw runtime exception
    that would kill the hotkey thread."""
    def _bad_query():
        raise RuntimeError("PortAudio enumeration failed")
    monkeypatch.setattr("kira.recorder.sd.query_devices", _bad_query)
    r = Recorder(input_device="ROG Theta")
    with pytest.raises(DeviceUnavailable):
        r.start()
    assert r._recording is False


# Hot-unplug-Recovery: PortAudio-Status-Frames + Stream-Cycle-Tests.

class _ActiveStream(_NoOpStream):
    """Mock-Stream der wie sd.InputStream eine .active-Property hat."""
    active = True


class _DeadStream(_NoOpStream):
    """Mock-Stream der nicht mehr aktiv ist (PortAudio hat ihn gestoppt)."""
    active = False


def test_callback_status_sets_dirty_flag_on_underflow():
    """USB-Mic-Hot-Unplug zeigt sich als status.input_underflow im
    nächsten PortAudio-Callback. Der Recorder muss das festhalten,
    sonst weiß der nächste start() nicht dass der Stream tot ist."""
    r = Recorder()

    class _Status:
        input_underflow = True
        input_overflow = False
        def __bool__(self): return True

    samples = np.zeros((100, 1), dtype=np.float32)
    r._callback(samples, 100, None, _Status())
    assert r._stream_dirty is True


def test_callback_overflow_does_not_set_dirty():
    """input_overflow ist häufig ein transient Spike direkt nach
    Stream-Start (PortAudio kalibriert Buffer-Größen). Würden wir den
    Stream darauf cyclen, würde JEDER F8 nach Boot den Pre-Roll-Buffer
    wegblasen und die ersten 50–200 ms gehen verloren."""
    r = Recorder()

    class _Status:
        input_underflow = False
        input_overflow = True
        def __bool__(self): return True

    samples = np.zeros((100, 1), dtype=np.float32)
    r._callback(samples, 100, None, _Status())
    assert r._stream_dirty is False


def test_callback_no_status_keeps_clean_flag():
    """Sanity: bei status=None (Normalbetrieb) bleibt der Stream clean."""
    r = Recorder()
    samples = np.zeros((100, 1), dtype=np.float32)
    r._callback(samples, 100, None, None)
    assert r._stream_dirty is False


def test_is_device_still_present_when_pinned_id_gone(monkeypatch):
    """Wenn das Device das wir per ID gepinnt haben aus
    sd.query_devices() verschwindet (USB ausgesteckt), muss die
    Health-Check-Methode False zurückgeben."""
    r = Recorder(input_device="ROG Theta")
    r._input_device = 1  # gepinnt auf Index 1
    monkeypatch.setattr(
        "kira.recorder.sd.query_devices",
        lambda: [{"name": "Realtek", "max_input_channels": 2}],  # nur Index 0
    )
    assert r._is_device_still_present() is False


def test_is_device_still_present_when_pinned_id_lost_input_channels(monkeypatch):
    """ASIO/MME re-enumeriert manchmal ohne Slot freizugeben — der Index
    bleibt, aber max_input_channels wird 0. Health-Check muss das als
    'weg' werten, sonst öffnet der nächste prewarm() einen Output-only-
    Stream und PortAudio crasht."""
    r = Recorder(input_device="ROG Theta")
    r._input_device = 0
    monkeypatch.setattr(
        "kira.recorder.sd.query_devices",
        lambda: [{"name": "ROG Theta", "max_input_channels": 0}],
    )
    assert r._is_device_still_present() is False


def test_is_device_still_present_returns_true_when_present(monkeypatch):
    """Sanity: Happy-Path — Device ist da, gibt True."""
    r = Recorder(input_device="ROG Theta")
    r._input_device = 0
    monkeypatch.setattr(
        "kira.recorder.sd.query_devices",
        lambda: [{"name": "ROG Theta", "max_input_channels": 1}],
    )
    assert r._is_device_still_present() is True


def test_cycle_stream_closes_when_dirty(monkeypatch):
    """Wenn der Callback dirty-flag gesetzt hat (input_underflow nach
    Hot-Unplug), muss _cycle_stream_if_unhealthy() den Stream schließen
    und _input_device zurücksetzen, damit der nächste start() neu
    resolved."""
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _ActiveStream())
    monkeypatch.setattr(
        "kira.recorder.sd.query_devices",
        lambda: [{"name": "ROG Theta", "max_input_channels": 1}],
    )
    r = Recorder(input_device="ROG Theta")
    r.prewarm()
    assert r._stream is not None
    r._stream_dirty = True
    cycled = r._cycle_stream_if_unhealthy()
    assert cycled is True
    assert r._stream is None
    assert r._input_device is None
    assert r._stream_dirty is False


def test_cycle_stream_closes_when_device_gone(monkeypatch):
    """Hot-Unplug ohne dirty-flag (z.B. weil noch kein Callback gefeuert
    hat seit dem Disconnect) — Stream ist active, Device aber weg.
    _cycle_stream_if_unhealthy() muss trotzdem schließen."""
    devices = {"current": [{"name": "ROG Theta", "max_input_channels": 1}]}
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _ActiveStream())
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: devices["current"])
    r = Recorder(input_device="ROG Theta")
    r.prewarm()
    assert r._stream is not None
    devices["current"] = []  # Mike steckt das USB-Kabel ab
    cycled = r._cycle_stream_if_unhealthy()
    assert cycled is True
    assert r._stream is None
    assert r._input_device is None


def test_cycle_stream_keeps_healthy_stream(monkeypatch):
    """Sanity: solange Stream active ist und Device da, NICHT cyclen.
    Sonst würden wir bei jedem F8 den Stream unnötig zumachen und neu
    öffnen — und damit den Pre-Roll-Buffer leerräumen, was die ersten
    50–200 ms jeder Aufnahme verlieren würde."""
    monkeypatch.setattr("kira.recorder.sd.InputStream", lambda **kw: _ActiveStream())
    monkeypatch.setattr(
        "kira.recorder.sd.query_devices",
        lambda: [{"name": "ROG Theta", "max_input_channels": 1}],
    )
    r = Recorder(input_device="ROG Theta")
    r.prewarm()
    assert r._stream is not None
    cycled = r._cycle_stream_if_unhealthy()
    assert cycled is False
    assert r._stream is not None


def test_start_recovers_after_hot_unplug(monkeypatch):
    """End-to-end: prewarm öffnet Stream, Mike zieht USB-Kabel,
    nächster Callback setzt dirty-flag, Mike steckt wieder ein,
    nächstes F8 (start()) cycelt den Stream und öffnet neu — KEINE
    DeviceUnavailable, KEINE Process-Kollision, normales Recording."""
    streams: list[_ActiveStream] = []
    devices = {"current": [{"name": "ROG Theta", "max_input_channels": 1}]}

    def _factory(**kw):
        s = _ActiveStream()
        streams.append(s)
        return s

    monkeypatch.setattr("kira.recorder.sd.InputStream", _factory)
    monkeypatch.setattr("kira.recorder.sd.query_devices", lambda: devices["current"])
    r = Recorder(input_device="ROG Theta")
    r.prewarm()
    assert len(streams) == 1
    # Hot-unplug-Sequenz: dirty flag wird gesetzt durch späteren callback
    r._stream_dirty = True
    # Mike steckt wieder ein → Device ist wieder enumeriert
    devices["current"] = [{"name": "ROG Theta", "max_input_channels": 1}]
    r.start()
    assert len(streams) == 2  # neuer Stream wurde geöffnet
    assert r._stream is streams[1]
    assert r._recording is True
