# © 2026 Mike Pollow, Digitalroots. Alle Rechte vorbehalten.
"""Tests für kira.correction_source. Das Format folgt JSONL-Chatverläufen:
eine JSON-Nachricht je Zeile, abgeschickte Nachrichten mit type == "user"."""
from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from kira.correction_source import SourceReader


def _line(obj) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def _user(text, ts="2026-09-22T18:15:40.000Z", **extra):
    return {"type": "user", "timestamp": ts,
            "message": {"role": "user", "content": text}, **extra}


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def test_only_human_messages_are_taken(tmp_path):
    _write(tmp_path / "a" / "s1.jsonl", [
        _line(_user("Bitte prüf das Log")),
        _line({"type": "assistant", "timestamp": "2026-09-22T18:15:41Z",
               "message": {"content": "ok"}}),
        _line(_user("Nebenstrang", isSidechain=True)),
        _line(_user("Systemhinweis", isMeta=True)),
        _line(_user("<command-name>/clear</command-name>")),
        _line(_user([{"type": "tool_result", "content": "x"}])),
        _line(_user([{"type": "text", "text": "Teil eins"},
                     {"type": "text", "text": "Teil zwei"}])),
    ])
    msgs = SourceReader([tmp_path]).read_new()
    assert [m.text for m in msgs] == ["Bitte prüf das Log", "Teil eins\nTeil zwei"]
    assert msgs[0].time == datetime(2026, 9, 22, 18, 15, 40, tzinfo=timezone.utc)


def test_second_read_returns_only_new_lines(tmp_path):
    path = tmp_path / "s1.jsonl"
    _write(path, [_line(_user("eins"))])
    reader = SourceReader([tmp_path])
    assert [m.text for m in reader.read_new()] == ["eins"]
    assert reader.bytes_read == path.stat().st_size
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_line(_user("zwei", ts="2026-09-22T18:16:00Z")))
    assert [m.text for m in reader.read_new()] == ["zwei"]
    again = SourceReader([tmp_path], reader.offsets)
    assert again.read_new() == []


def test_incomplete_last_line_waits_for_the_next_run(tmp_path):
    path = tmp_path / "s1.jsonl"
    full = _line(_user("fertig"))
    _write(path, [full[:-10]])
    reader = SourceReader([tmp_path])
    assert reader.read_new() == []
    path.write_text(full, encoding="utf-8")
    assert [m.text for m in reader.read_new()] == ["fertig"]


def test_huge_lines_are_skipped_without_losing_the_rest(tmp_path):
    big = _line({"type": "user", "timestamp": "2026-09-22T18:00:00Z",
                 "message": {"content": [{"type": "tool_result", "content": "x" * 2_100_000}]}})
    _write(tmp_path / "s1.jsonl", [big, _line(_user("danach"))])
    assert [m.text for m in SourceReader([tmp_path]).read_new()] == ["danach"]


def test_shrunk_file_is_read_from_the_start(tmp_path):
    path = tmp_path / "s1.jsonl"
    _write(path, [_line(_user("eins")), _line(_user("zwei"))])
    reader = SourceReader([tmp_path])
    reader.read_new()
    _write(path, [_line(_user("neu"))])
    assert [m.text for m in reader.read_new()] == ["neu"]


def test_missing_directory_is_skipped(tmp_path):
    assert SourceReader([tmp_path / "fehlt"]).read_new() == []


def test_files_older_than_modified_since_are_ignored(tmp_path):
    path = tmp_path / "alt.jsonl"
    _write(path, [_line(_user("alt"))])
    old = time.time() - 3 * 86400
    os.utime(path, (old, old))
    since = datetime.now(timezone.utc) - timedelta(days=1)
    assert SourceReader([tmp_path]).read_new(modified_since=since) == []


def test_missing_directory_is_logged(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        result = SourceReader([tmp_path / "fehlt"]).read_new()
    assert result == []
    assert "nicht erreichbar" in caplog.text


def test_non_dict_message_is_skipped_without_losing_other_files(tmp_path):
    _write(tmp_path / "a.jsonl", [
        _line({"type": "user", "timestamp": "2026-09-22T18:00:00Z", "message": "kein Objekt"}),
    ])
    _write(tmp_path / "b.jsonl", [
        _line(_user("bleibt")),
    ])
    msgs = SourceReader([tmp_path]).read_new()
    assert [m.text for m in msgs] == ["bleibt"]


def test_messages_from_several_files_are_sorted_by_time(tmp_path):
    _write(tmp_path / "a.jsonl", [
        _line(_user("später", ts="2026-09-22T18:10:00Z")),
    ])
    _write(tmp_path / "b.jsonl", [
        _line(_user("früher", ts="2026-09-22T18:05:00Z")),
    ])
    msgs = SourceReader([tmp_path]).read_new()
    assert [m.text for m in msgs] == ["früher", "später"]
