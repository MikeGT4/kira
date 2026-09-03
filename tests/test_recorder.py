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


def test_resolve_device_matches_input_by_substring(monkeypatch):
    import kira.recorder as rec
    monkeypatch.setattr(rec.sd, "query_devices", lambda: [
        {"name": "MacBook Air Speakers", "max_input_channels": 0},
        {"name": "Shure MV7+", "max_input_channels": 1},
        {"name": "MacBook Air Microphone", "max_input_channels": 1},
    ])
    assert rec.Recorder(input_device="shure")._resolve_device() == 1
    assert rec.Recorder(input_device="Air Micro")._resolve_device() == 2
    assert rec.Recorder(input_device="Speakers")._resolve_device() is None
    assert rec.Recorder(input_device=None)._resolve_device() is None
