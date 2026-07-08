"""LRC formatting (pure) + /status and /export routes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import routes  # noqa: E402

STATUS = "/api/plugins/lyrics_sync/status"
EXPORT = "/api/plugins/lyrics_sync/export"


# ── _format_lrc / _format_lrc_word_level (pure) ────────────────────────────────

def test_format_lrc_basic_timestamps():
    segments = [{"start": 0.0, "text": "Hello"}, {"start": 65.5, "text": "World"}]
    assert routes._format_lrc(segments) == "[00:00.00]Hello\n[01:05.50]World\n"


def test_format_lrc_empty_segments():
    assert routes._format_lrc([]) == "\n"


def test_format_lrc_word_level_includes_inline_word_timestamps():
    segments = [{
        "start": 1.0, "text": "hi there",
        "words": [{"start": 1.0, "text": "hi"}, {"start": 1.5, "text": "there"}],
    }]
    lrc = routes._format_lrc_word_level(segments)
    assert lrc == "[00:01.00]<00:01.00>hi <00:01.50>there\n"


def test_format_lrc_word_level_falls_back_to_line_text_without_words():
    segments = [{"start": 2.0, "text": "no word timing"}]
    assert routes._format_lrc_word_level(segments) == "[00:02.00]no word timing\n"


# ── /status ─────────────────────────────────────────────────────────────────

def test_status_no_server_configured(client):
    r = client.get(STATUS)
    assert r.status_code == 200
    assert r.json() == {"available": False, "reason": "No demucs server configured"}


def test_status_reports_available_server(client, config_dir, monkeypatch):
    (config_dir / "config.json").write_text('{"demucs_server_url": "http://localhost:9000"}')

    import requests

    class FakeResp:
        status_code = 200

    monkeypatch.setattr(requests, "get", lambda url, timeout=5: FakeResp())
    r = client.get(STATUS)
    assert r.json() == {"available": True, "server_url": "http://localhost:9000"}


def test_status_reports_server_error_code(client, config_dir, monkeypatch):
    (config_dir / "config.json").write_text('{"demucs_server_url": "http://localhost:9000"}')
    import requests

    class FakeResp:
        status_code = 500

    monkeypatch.setattr(requests, "get", lambda url, timeout=5: FakeResp())
    r = client.get(STATUS)
    assert r.json() == {"available": False, "reason": "Server returned 500"}


def test_status_reports_connection_exception(client, config_dir, monkeypatch):
    (config_dir / "config.json").write_text('{"demucs_server_url": "http://localhost:9000"}')
    import requests

    def raise_conn(url, timeout=5):
        raise ConnectionError("boom")
    monkeypatch.setattr(requests, "get", raise_conn)
    r = client.get(STATUS)
    assert r.json()["available"] is False
    assert "boom" in r.json()["reason"]


# ── /export ─────────────────────────────────────────────────────────────────

def test_export_requires_segments(client):
    r = client.post(EXPORT, json={"segments": []})
    assert r.status_code == 400


def test_export_produces_lrc_with_header(client):
    r = client.post(EXPORT, json={
        "segments": [{"start": 0.0, "text": "Hello"}],
        "title": "My Song", "artist": "My Band",
    })
    assert r.status_code == 200
    body = r.text
    assert "[ti:My Song]" in body
    assert "[ar:My Band]" in body
    assert "[by:Slopsmith Lyrics Sync]" in body
    assert "[00:00.00]Hello" in body
    assert "attachment" in r.headers["content-disposition"]
    assert "My Band - My Song.lrc" in r.headers["content-disposition"]


def test_export_omits_header_fields_when_absent(client):
    r = client.post(EXPORT, json={"segments": [{"start": 0.0, "text": "Hi"}]})
    body = r.text
    assert "[ti:" not in body
    assert "[ar:" not in body
    assert "lyrics.lrc" in r.headers["content-disposition"]


def test_export_sanitizes_slashes_in_filename(client):
    r = client.post(EXPORT, json={
        "segments": [{"start": 0.0, "text": "Hi"}],
        "title": "A/B\\C",
    })
    assert "A_B_C.lrc" in r.headers["content-disposition"]
