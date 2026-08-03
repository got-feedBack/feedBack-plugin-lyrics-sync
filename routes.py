"""Lyrics Sync plugin — generate time-synced LRC from plain text lyrics + vocals stem."""

import json
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

_config_dir = None
_get_dlc_dir = None

SLOPPAK_CACHE_DIR = None


def _is_approved_demucs_url(url: object) -> bool:
    """Allow only local/private HTTP(S) Demucs server destinations."""
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return False
    hostname = parsed.hostname
    if not hostname or parsed.query or parsed.fragment:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _get_demucs_server_url() -> str | None:
    """Get the configured demucs server URL from config.json."""
    config_file = _config_dir / "config.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            url = cfg.get("demucs_server_url", "")
            if _is_approved_demucs_url(url):
                return url.rstrip("/")
        except Exception:
            pass
    return None


def _find_vocals_stem(filename: str) -> Path | None:
    """Find the vocals stem file for a sloppak song."""
    import sloppak as sloppak_mod

    dlc = _get_dlc_dir()
    if not dlc:
        return None

    song_path = dlc / filename
    if not sloppak_mod.is_sloppak(song_path):
        return None

    source_dir = sloppak_mod.resolve_source_dir(filename, dlc, SLOPPAK_CACHE_DIR)
    manifest = sloppak_mod.load_manifest(song_path)

    for s in manifest.get("stems", []) or []:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id", "")).lower()
        sfile = str(s.get("file", ""))
        if sid == "vocals" and sfile:
            vocals_path = source_dir / sfile
            if vocals_path.exists():
                return vocals_path
    return None


def _format_lrc(segments: list[dict]) -> str:
    """Convert alignment segments to standard LRC format."""
    lines = []
    for seg in segments:
        t = seg["start"]
        minutes = int(t // 60)
        seconds = t % 60
        lines.append(f"[{minutes:02d}:{seconds:05.2f}]{seg['text']}")
    return "\n".join(lines) + "\n"


def _format_lrc_word_level(segments: list[dict]) -> str:
    """Convert word-level alignment segments to enhanced LRC format."""
    lines = []
    for seg in segments:
        t = seg["start"]
        minutes = int(t // 60)
        seconds = t % 60
        text = seg["text"]
        # Word-level: include inline timestamps for each word
        if "words" in seg:
            word_parts = []
            for w in seg["words"]:
                wt = w["start"]
                wm = int(wt // 60)
                ws = wt % 60
                word_parts.append(f"<{wm:02d}:{ws:05.2f}>{w['text']}")
            text = " ".join(word_parts)
        lines.append(f"[{minutes:02d}:{seconds:05.2f}]{text}")
    return "\n".join(lines) + "\n"


def setup(app: FastAPI, context: dict):
    global _config_dir, _get_dlc_dir, SLOPPAK_CACHE_DIR

    _config_dir = context["config_dir"]
    _get_dlc_dir = context["get_dlc_dir"]
    static_dir = Path(os.environ.get("STATIC_DIR", "/app/static"))
    SLOPPAK_CACHE_DIR = static_dir / "sloppak_cache"

    @app.get("/api/plugins/lyrics_sync/status")
    def ls_status():
        """Check if the alignment server is reachable AND actually ready to
        align — not just that /health returns 200.

        The demucs-server's /health responds 200 with `status: "ok"` as soon
        as the process is up, well before its models finish loading — during
        that window its `warmup` block reports fields like `whisperx:
        "downloading"`. Treating any 200 as "ready" (the previous behavior)
        showed a green "Alignment server ready" notice while a request would
        still hit the server mid-warmup, surfacing as a confusing
        "Cannot connect to alignment server" once the user actually clicked
        Align. `/align` needs whisperx (transcription, used for VAD-anchored
        alignment windows — see the demucs-server's own /align docs) loaded
        first; per-language aligners load lazily on demand and are not
        gated on here.
        """
        url = _get_demucs_server_url()
        if not url:
            return {"available": False, "reason": "No demucs server configured"}
        try:
            import requests
            resp = requests.get(f"{url}/health", timeout=5, allow_redirects=False)
            if resp.status_code != 200:
                return {"available": False, "reason": f"Server returned {resp.status_code}"}
            body = resp.json()
            warmup = body.get("warmup") or {}
            whisperx_state = warmup.get("whisperx")
            if whisperx_state != "ready":
                if whisperx_state in {"downloading", "loading", "starting", "warming_up"}:
                    reason = (
                        f"Alignment model still loading ({whisperx_state}) "
                        "— try again in a moment."
                    )
                else:
                    reason = f"Alignment model is not ready ({whisperx_state or 'unknown'})"
                return {
                    "available": False,
                    "reason": reason,
                }
            return {"available": True, "server_url": url}
        except Exception as e:
            return {"available": False, "reason": str(e)}

    @app.post("/api/plugins/lyrics_sync/align")
    def ls_align(data: dict):
        """Align lyrics text against a sloppak song's vocals stem.

        Expects: {"filename": str, "lyrics_text": str, "language": str?, "granularity": str?}
        Returns: {"segments": [{"start": float, "end": float, "text": str}, ...]}
        """
        filename = data.get("filename", "")
        lyrics_text = data.get("lyrics_text", "").strip()
        language = data.get("language", "")
        granularity = data.get("granularity", "line")

        if not filename:
            return JSONResponse({"error": "filename required"}, 400)
        if not lyrics_text:
            return JSONResponse({"error": "lyrics_text required"}, 400)

        # Find the vocals stem
        vocals_path = _find_vocals_stem(filename)
        if not vocals_path:
            return JSONResponse(
                {"error": "No vocals stem found. Song must be a sloppak with split stems."},
                400,
            )

        # Get demucs server URL
        server_url = _get_demucs_server_url()
        if not server_url:
            return JSONResponse({"error": "No demucs server configured"}, 400)

        # Send vocals + text to the alignment server
        import requests
        try:
            with open(vocals_path, "rb") as f:
                resp = requests.post(
                    f"{server_url}/align",
                    files={"file": (vocals_path.name, f, "audio/ogg")},
                    data={
                        "text": lyrics_text,
                        "language": language,
                        "granularity": granularity,
                    },
                    timeout=300,
                    allow_redirects=False,
                )

            if resp.status_code != 200:
                return JSONResponse(
                    {"error": f"Alignment server error: {resp.text[:500]}"},
                    502,
                )

            result = resp.json()
            if "error" in result:
                return JSONResponse(
                    {"error": f"Alignment failed: {result['error']}"},
                    502,
                )

            return result
        except requests.Timeout:
            return JSONResponse({"error": "Alignment request timed out"}, 504)
        except requests.ConnectionError:
            return JSONResponse({"error": "Cannot connect to alignment server"}, 502)

    @app.post("/api/plugins/lyrics_sync/export")
    def ls_export(data: dict):
        """Export alignment segments as an LRC file.

        Expects: {"segments": [...], "title": str?, "artist": str?}
        Returns: LRC file download.
        """
        segments = data.get("segments", [])
        if not segments:
            return JSONResponse({"error": "No segments provided"}, 400)

        title = data.get("title", "")
        artist = data.get("artist", "")

        # Build LRC header + body
        header_lines = []
        if title:
            header_lines.append(f"[ti:{title}]")
        if artist:
            header_lines.append(f"[ar:{artist}]")
        header_lines.append("[by:Slopsmith Lyrics Sync]")
        header = "\n".join(header_lines) + "\n"

        lrc = header + _format_lrc(segments)

        safe_name = f"{artist} - {title}".strip(" -") or "lyrics"
        safe_name = safe_name.replace("/", "_").replace("\\", "_")

        return Response(
            content=lrc,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}.lrc"',
            },
        )

    @app.post("/api/plugins/lyrics_sync/save")
    def ls_save(data: dict):
        """Save synced lyrics into the sloppak manifest for playback display.

        Expects: {"filename": str, "segments": [...]}
        Writes a lyrics JSON file and updates the sloppak manifest.
        """
        import sloppak as sloppak_mod

        filename = data.get("filename", "")
        segments = data.get("segments", [])

        if not filename or not segments:
            return JSONResponse({"error": "filename and segments required"}, 400)

        dlc = _get_dlc_dir()
        if not dlc:
            return JSONResponse({"error": "DLC folder not configured"}, 400)

        song_path = dlc / filename
        if not sloppak_mod.is_sloppak(song_path):
            return JSONResponse({"error": "Not a sloppak file"}, 400)

        source_dir = sloppak_mod.resolve_source_dir(filename, dlc, SLOPPAK_CACHE_DIR)

        # Convert alignment segments to the sloppak lyrics format:
        # [{"t": time, "d": duration, "w": word}, ...]
        # For line-level: each segment becomes one entry with the full line as "w"
        lyrics_data = []
        for seg in segments:
            lyrics_data.append({
                "t": round(seg["start"], 3),
                "d": round(seg["end"] - seg["start"], 3),
                "w": seg["text"],
            })

        # Write lyrics JSON file
        lyrics_path = source_dir / "lyrics.json"
        lyrics_path.write_text(json.dumps(lyrics_data, indent=2), encoding="utf-8")

        # Update manifest to reference the lyrics file
        manifest_path = source_dir / "manifest.yaml"
        if manifest_path.exists():
            try:
                import yaml
            except ImportError:
                # Fallback: read and patch YAML manually
                text = manifest_path.read_text(encoding="utf-8")
                if "lyrics:" not in text:
                    text = text.rstrip() + "\nlyrics: lyrics.json\n"
                    manifest_path.write_text(text, encoding="utf-8")
            else:
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                manifest["lyrics"] = "lyrics.json"
                manifest_path.write_text(
                    yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
                    encoding="utf-8",
                )

        return {"ok": True, "lyrics_count": len(lyrics_data)}
