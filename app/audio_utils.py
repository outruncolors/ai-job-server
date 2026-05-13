from __future__ import annotations

import wave
from pathlib import Path


def _silence_bytes(nchannels: int, sampwidth: int, framerate: int, duration_ms: int) -> bytes:
    n_frames = int(framerate * duration_ms / 1000)
    return b"\x00" * (n_frames * nchannels * sampwidth)


def merge_wav_files(
    segment_paths: list[Path],
    delay_ms_list: list[int],
    output_path: Path,
) -> None:
    """
    Merge WAV files into one, inserting silence after each segment.

    delay_ms_list[i] is the silence added after segment_paths[i].
    The last segment's delay is always skipped (no trailing silence).
    Raises ValueError for empty input; RuntimeError for mismatched WAV params.
    """
    if not segment_paths:
        raise ValueError("No segments to merge")

    with wave.open(str(segment_paths[0]), "rb") as ref:
        nchannels = ref.getnchannels()
        sampwidth = ref.getsampwidth()
        framerate = ref.getframerate()

    with wave.open(str(output_path), "wb") as out:
        out.setnchannels(nchannels)
        out.setsampwidth(sampwidth)
        out.setframerate(framerate)

        last = len(segment_paths) - 1
        for i, (seg_path, delay_ms) in enumerate(zip(segment_paths, delay_ms_list)):
            with wave.open(str(seg_path), "rb") as seg:
                if (seg.getnchannels() != nchannels
                        or seg.getsampwidth() != sampwidth
                        or seg.getframerate() != framerate):
                    raise RuntimeError(
                        f"WAV params of {seg_path.name} differ from first segment "
                        f"({seg.getframerate()}Hz/{seg.getnchannels()}ch vs "
                        f"{framerate}Hz/{nchannels}ch)"
                    )
                out.writeframes(seg.readframes(seg.getnframes()))
            if i < last and delay_ms > 0:
                out.writeframes(_silence_bytes(nchannels, sampwidth, framerate, delay_ms))
