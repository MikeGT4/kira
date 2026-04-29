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
