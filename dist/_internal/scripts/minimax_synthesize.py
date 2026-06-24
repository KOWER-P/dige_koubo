#!/usr/bin/env python3
"""Synthesize an MP3 with MiniMax T2A using the fixed custom voice."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
DEFAULT_MODEL = "speech-2.8-hd"
DEFAULT_VOICE_ID = "moss_audio_3a90a07a-6eb8-11f1-a8f5-12c8f1e32e55"


def read_windows_user_env(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return str(value).strip() or None


def read_api_key(args: argparse.Namespace) -> str | None:
    return (
        args.api_key
        or os.environ.get("MINIMAX_API_KEY")
        or read_windows_user_env("MINIMAX_API_KEY")
    )


def read_text(args: argparse.Namespace) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()
    if args.text:
        return args.text.strip()
    data = sys.stdin.read().strip()
    if data:
        return data
    raise SystemExit("No text provided. Use --text, --text-file, or stdin.")


def ffprobe_duration(path: Path) -> str | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def synthesize(args: argparse.Namespace) -> dict:
    api_key = read_api_key(args)
    if not api_key:
        raise SystemExit("Missing MiniMax API key. Set MINIMAX_API_KEY or pass --api-key.")

    text = read_text(args)
    body = {
        "model": args.model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": args.voice_id,
            "speed": args.speed,
            "vol": args.volume,
            "pitch": args.pitch,
            "emotion": args.emotion,
        },
        "audio_setting": {
            "sample_rate": args.sample_rate,
            "bitrate": args.bitrate,
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": False,
    }
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc

    result = json.loads(raw)
    base = result.get("base_resp") or {}
    if base.get("status_code") != 0:
        raise SystemExit(json.dumps(base, ensure_ascii=False))

    audio_hex = ((result.get("data") or {}).get("audio") or "").strip()
    if not audio_hex:
        raise SystemExit("MiniMax returned success but no data.audio field.")

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes.fromhex(audio_hex))

    extra = result.get("extra_info") or {}
    return {
        "ok": True,
        "output_file": str(out),
        "size_bytes": out.stat().st_size,
        "duration_sec": ffprobe_duration(out),
        "api_audio_length_ms": extra.get("audio_length"),
        "word_count": extra.get("word_count"),
        "usage_characters": extra.get("usage_characters"),
        "trace_id": result.get("trace_id"),
        "voice_id": args.voice_id,
        "model": args.model,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="Narration text to synthesize.")
    parser.add_argument("--text-file", help="UTF-8 text file containing narration.")
    parser.add_argument("--out", default="minimax_voice.mp3", help="Output MP3 path.")
    parser.add_argument("--api-key", help="MiniMax API key. Prefer MINIMAX_API_KEY.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--voice-id", default=DEFAULT_VOICE_ID)
    parser.add_argument("--emotion", default="happy")
    parser.add_argument("--speed", type=float, default=1.1)
    parser.add_argument("--volume", type=float, default=1)
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--sample-rate", type=int, default=32000)
    parser.add_argument("--bitrate", type=int, default=128000)
    parser.add_argument("--timeout", type=int, default=120)
    summary = synthesize(parser.parse_args())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
