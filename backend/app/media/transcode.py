"""Video transcoding for IG / Threads target formats via ffmpeg.

Issue #22 DoD:
- Detect aspect ratio of the original
- Auto-pad (letterbox/pillarbox) to exact target size
- Write variants under data/media/variants/ and record paths in
  MediaAsset.variants_json (keys: reels_9x16, feed_1x1, feed_4x5, threads_9x16)

Targets:
- IG Reels / Threads 9:16: 1080x1920, h264+AAC, ≤90s
- IG Feed 1:1: 1080x1080
- IG Feed 4:5: 1080x1350
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("media.transcode")

DATA_ROOT = Path("data")
VARIANTS_DIR = DATA_ROOT / "media" / "variants"

# (variant_key, target_width, target_height, max_duration_sec or None)
TARGETS: list[tuple[str, int, int, float | None]] = [
    ("reels_9x16", 1080, 1920, 90.0),
    ("feed_1x1", 1080, 1080, None),
    ("feed_4x5", 1080, 1350, None),
    ("threads_9x16", 1080, 1920, 90.0),
]


@dataclass(frozen=True)
class ProbeInfo:
    width: int
    height: int
    duration: float
    codec: str
    has_audio: bool


class TranscodeError(RuntimeError):
    """Raised when ffprobe/ffmpeg fails or binary is missing."""


def _ensure_bins() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise TranscodeError("ffmpeg/ffprobe not found on PATH")


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    log.debug("run: %s", " ".join(cmd))
    try:
        return subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise TranscodeError("ffmpeg/ffprobe not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "")[-2000:]
        raise TranscodeError(f"command failed ({exc.returncode}): {stderr}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f"command timed out after {timeout}s") from exc


def probe(path: Path) -> ProbeInfo:
    """Return width/height/duration/codec for the first video stream."""
    _ensure_bins()
    if not path.exists():
        raise TranscodeError(f"source missing: {path}")
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = _run(cmd, timeout=60)
    data = json.loads(result.stdout or "{}")
    video = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video is None:
        raise TranscodeError(f"no video stream in {path}")
    width = int(video["width"])
    height = int(video["height"])
    duration_raw = data.get("format", {}).get("duration") or video.get("duration") or 0
    duration = float(duration_raw)
    codec = str(video.get("codec_name") or "unknown")
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return ProbeInfo(
        width=width,
        height=height,
        duration=duration,
        codec=codec,
        has_audio=has_audio,
    )


def aspect_ratio(width: int, height: int) -> float:
    if height <= 0:
        return 0.0
    return width / height


def _build_vf(src_w: int, src_h: int, tw: int, th: int) -> str:
    """Scale to fit inside target, then pad with black to exact size (centered)."""
    # force_original_aspect_ratio=decrease keeps the whole frame; pad fills gaps.
    return (
        f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1"
    )


def transcode_one(
    src: Path,
    key: str,
    tw: int,
    th: int,
    max_duration: float | None,
    *,
    probe_info: ProbeInfo | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Transcode one variant. Returns path relative to data/."""
    _ensure_bins()
    info = probe_info or probe(src)
    dest_dir = out_dir or VARIANTS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{uuid.uuid4().hex}_{key}.mp4"
    out_path = dest_dir / out_name
    vf = _build_vf(info.width, info.height, tw, th)

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if max_duration is not None and info.duration > max_duration:
        cmd.extend(["-t", str(max_duration)])
    if info.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "128k", "-ac", "2"])
    else:
        cmd.append("-an")
    cmd.append(str(out_path))

    _run(cmd)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise TranscodeError(f"ffmpeg produced empty output for {key}")
    # relative to data/
    try:
        rel = out_path.relative_to(DATA_ROOT)
    except ValueError:
        rel = Path("media") / "variants" / out_name
    return rel


def transcode_all(
    src: Path,
    keys: list[str] | None = None,
    *,
    out_dir: Path | None = None,
) -> dict[str, str]:
    """Produce requested variants. Returns {key: relative_path_str}."""
    info = probe(src)
    selected = [t for t in TARGETS if keys is None or t[0] in keys]
    if not selected:
        raise TranscodeError(f"no matching targets for keys={keys!r}")
    variants: dict[str, str] = {}
    for key, tw, th, max_dur in selected:
        rel = transcode_one(
            src,
            key,
            tw,
            th,
            max_dur,
            probe_info=info,
            out_dir=out_dir,
        )
        variants[key] = str(rel).replace("\\", "/")
        log.info("transcoded %s -> %s (src %sx%s %.1fs)", key, rel, info.width, info.height, info.duration)
    return variants
