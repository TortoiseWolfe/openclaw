#!/usr/bin/env python3
"""Generate narration audio from text using Microsoft Edge TTS (free, no API key).

Optionally emits word-boundary timing JSON for per-bullet sync.
"""

import argparse
import asyncio
import json
import sys

import edge_tts

DEFAULT_VOICE = "en-US-GuyNeural"


async def generate(
    text: str,
    output: str,
    voice: str,
    subtitles: bool,
    timing_output: str | None,
) -> None:
    communicate = edge_tts.Communicate(text, voice)

    if timing_output:
        # Stream to collect audio bytes and timing events.
        # edge_tts v7+ emits SentenceBoundary; older versions emit WordBoundary.
        boundaries: list[dict] = []
        audio_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                boundaries.append({
                    "offset": chunk["offset"],      # time in 100ns ticks
                    "duration": chunk["duration"],   # duration in 100ns ticks
                    "text": chunk["text"],           # the spoken text
                })
        with open(output, "wb") as f:
            for data in audio_chunks:
                f.write(data)
        with open(timing_output, "w") as f:
            json.dump(boundaries, f)
        print(f"Timing: {len(boundaries)} boundaries → {timing_output}", file=sys.stderr)
    else:
        await communicate.save(output)

    if subtitles:
        vtt_path = output.rsplit(".", 1)[0] + ".vtt"
        sub = edge_tts.SubMaker()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "WordBoundary":
                sub.feed(chunk)
        with open(vtt_path, "w") as f:
            f.write(sub.generate_subs())
        print(f"Subtitles: {vtt_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate narration audio via Edge TTS")
    parser.add_argument("--text", required=True, help="Text to narrate")
    parser.add_argument("--output", required=True, help="Output audio file path (.mp3)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help=f"Edge TTS voice (default: {DEFAULT_VOICE})")
    parser.add_argument("--subtitles", action="store_true", help="Also generate .vtt subtitle file")
    parser.add_argument("--timing-output", help="Write word boundary timing JSON to this path")
    args = parser.parse_args()

    asyncio.run(generate(args.text, args.output, args.voice, args.subtitles, args.timing_output))
    print(f"Audio: {args.output}")


if __name__ == "__main__":
    main()
