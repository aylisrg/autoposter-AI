"""Tests for video transcode helpers (#22).

ffmpeg/ffprobe are mocked so CI does not need real binaries or sample videos.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.media.transcode import (
    ProbeInfo,
    TranscodeError,
    aspect_ratio,
    probe,
    transcode_all,
    transcode_one,
)


def test_aspect_ratio():
    assert aspect_ratio(1920, 1080) == pytest.approx(16 / 9)
    assert aspect_ratio(1080, 1920) == pytest.approx(9 / 16)
    assert aspect_ratio(100, 0) == 0.0


def test_probe_parses_ffprobe_json(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")

    payload = {
        "streams": [
            {"codec_type": "video", "width": 1280, "height": 720, "codec_name": "h264", "duration": "12.5"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "12.5"},
    }

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "ffprobe"
        m = MagicMock()
        m.stdout = json.dumps(payload)
        m.returncode = 0
        return m

    monkeypatch.setattr("app.media.transcode.subprocess.run", fake_run)
    monkeypatch.setattr("app.media.transcode.shutil.which", lambda _: "/usr/bin/ffprobe")

    info = probe(src)
    assert info.width == 1280
    assert info.height == 720
    assert info.duration == 12.5
    assert info.has_audio is True
    assert info.codec == "h264"


def test_probe_missing_video_stream(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        m = MagicMock()
        m.stdout = json.dumps({"streams": [{"codec_type": "audio"}], "format": {}})
        return m

    monkeypatch.setattr("app.media.transcode.subprocess.run", fake_run)
    monkeypatch.setattr("app.media.transcode.shutil.which", lambda _: "/usr/bin/ffprobe")

    with pytest.raises(TranscodeError, match="no video stream"):
        probe(src)


def test_transcode_one_builds_ffmpeg_cmd(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    out_dir = tmp_path / "variants"
    out_dir.mkdir()

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        # Simulate ffmpeg writing the last arg
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"mp4data")
        m = MagicMock()
        m.stdout = ""
        return m

    monkeypatch.setattr("app.media.transcode.subprocess.run", fake_run)
    monkeypatch.setattr("app.media.transcode.shutil.which", lambda _: "/usr/bin/ffmpeg")

    info = ProbeInfo(width=1920, height=1080, duration=120.0, codec="h264", has_audio=True)
    rel = transcode_one(
        src,
        "reels_9x16",
        1080,
        1920,
        90.0,
        probe_info=info,
        out_dir=out_dir,
    )
    assert rel.name.endswith("_reels_9x16.mp4") or "reels_9x16" in str(rel)
    assert calls, "ffmpeg should have been invoked"
    ffmpeg_cmd = calls[0]
    assert ffmpeg_cmd[0] == "ffmpeg"
    assert "-vf" in ffmpeg_cmd
    vf = ffmpeg_cmd[ffmpeg_cmd.index("-vf") + 1]
    assert "1080:1920" in vf
    assert "pad=" in vf
    assert "-t" in ffmpeg_cmd  # duration > 90 → trim
    assert "90.0" in ffmpeg_cmd or "90" in " ".join(ffmpeg_cmd)


def test_transcode_all_writes_all_keys(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    out_dir = tmp_path / "variants"
    out_dir.mkdir()

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            m = MagicMock()
            m.stdout = json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "video",
                            "width": 720,
                            "height": 1280,
                            "codec_name": "h264",
                        }
                    ],
                    "format": {"duration": "8.0"},
                }
            )
            return m
        # ffmpeg
        Path(cmd[-1]).write_bytes(b"x")
        return MagicMock(stdout="")

    monkeypatch.setattr("app.media.transcode.subprocess.run", fake_run)
    monkeypatch.setattr("app.media.transcode.shutil.which", lambda _: "/bin/true")

    variants = transcode_all(src, out_dir=out_dir)
    assert set(variants.keys()) == {"reels_9x16", "feed_1x1", "feed_4x5", "threads_9x16"}
    for path in variants.values():
        assert path.endswith(".mp4")


def test_transcode_rejects_unknown_keys(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")

    def fake_run(cmd, **kwargs):
        m = MagicMock()
        m.stdout = json.dumps(
            {
                "streams": [{"codec_type": "video", "width": 100, "height": 100, "codec_name": "h264"}],
                "format": {"duration": "1"},
            }
        )
        return m

    monkeypatch.setattr("app.media.transcode.subprocess.run", fake_run)
    monkeypatch.setattr("app.media.transcode.shutil.which", lambda _: "/bin/true")

    with pytest.raises(TranscodeError, match="no matching targets"):
        transcode_all(src, keys=["not_a_real_key"])
