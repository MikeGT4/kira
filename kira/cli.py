"""CLI: transcribe a WAV file and polish it for a given mode. Debug helper."""
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path
import soundfile as sf
from kira.config import load_config
from kira.transcriber import Transcriber
from kira.styler import Styler


async def run(wav_path: Path, mode: str) -> None:
    cfg = load_config()
    audio, sr = sf.read(wav_path, dtype="float32")
    if sr != 16000:
        print(f"warning: sample rate {sr} != 16000, resampling not implemented — expect bad quality", file=sys.stderr)
    print("Transcribing...", file=sys.stderr)
    t = Transcriber(cfg)
    result = t.transcribe(audio)
    print(f"Raw ({result.language}): {result.text}", file=sys.stderr)
    print("Polishing...", file=sys.stderr)
    styler = Styler(cfg)
    polished = await styler.polish(result.text, mode=mode)
    print(polished)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kira-once", description="Transcribe+polish a WAV")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--mode", default="plain", choices=["email", "chat", "terminal", "code", "plain"])
    args = parser.parse_args()
    asyncio.run(run(args.wav, args.mode))


if __name__ == "__main__":
    main()
