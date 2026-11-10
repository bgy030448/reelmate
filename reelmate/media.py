import json
import os
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from .common import ROOT, ReelMateError


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
INPUT_OPTIONS = ["-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm"]


def executable(name):
    suffix = ".exe" if os.name == "nt" else ""
    configured = os.getenv("REELMATE_FFMPEG_BIN")
    if configured:
        binary = Path(configured) / (name + suffix)
        if binary.is_file():
            return str(binary.resolve())
        raise ReelMateError(f"REELMATE_FFMPEG_BIN에서 {name}을 찾을 수 없습니다.")
    system = shutil.which(name)
    if system:
        return system
    binaries = sorted((ROOT / ".tools" / "ffmpeg").glob(f"*/bin/{name}{suffix}"))
    if binaries:
        return str(binaries[-1])
    raise ReelMateError(f"{name}을 찾을 수 없습니다. Windows 설치 스크립트 또는 README를 확인하세요.")


def run(name, args, *, cwd=None, timeout=120):
    try:
        completed = subprocess.run(
            [executable(name), *map(str, args)],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ReelMateError(f"{name} 처리 시간이 초과되었습니다. 짧은 영상으로 다시 시도하세요.") from exc
    except OSError as exc:
        raise ReelMateError(f"{name}을 실행할 수 없습니다. 설치 상태를 확인하세요.") from exc
    if completed.returncode:
        raise ReelMateError(f"{name}이 파일을 처리하지 못했습니다. 영상 형식·코덱과 설치 상태를 확인하세요.")
    return completed


def probe(path):
    output = run("ffprobe", ["-v", "error", *INPUT_OPTIONS, "-show_format", "-show_streams",
                            "-of", "json", path], timeout=25)
    metadata = json.loads(output.stdout)
    streams = metadata.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video" and
                  not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ReelMateError("재생 가능한 영상 스트림이 없습니다.")
    try:
        fps = float(Fraction(video["avg_frame_rate"]))
        duration = float(video.get("duration") or metadata["format"]["duration"])
        width, height = video["width"], video["height"]
        rotation = next((int(d["rotation"]) for d in video.get("side_data_list", [])
                         if "rotation" in d), 0) % 360
    except (ValueError, ZeroDivisionError, KeyError, OverflowError) as exc:
        raise ReelMateError("영상의 길이, 해상도 또는 프레임레이트를 읽을 수 없습니다.") from exc
    if not 0.1 <= duration <= 120 or not 0 < fps <= 240 or not 0 < width * height <= 4096 * 4096:
        raise ReelMateError("0.1~120초, 240fps 이하, 최대 약 1,678만 화소의 영상을 사용하세요.")
    if rotation in (90, 270):
        width, height = height, width
    return {
        "duration": round(duration, 3),
        "fps": round(fps, 3),
        "width": width,
        "height": height,
        "codec": video["codec_name"],
        "rotation": rotation,
        "has_audio": any(s["codec_type"] == "audio" for s in streams),
        "video_index": video["index"],
        "subtitle_index": next((s["index"] for s in streams
                                if s["codec_type"] == "subtitle" and
                                s.get("codec_name") in {"mov_text", "subrip", "ass", "webvtt"}), None),
    }


def thumbnail(source, output, at, video_index):
    run("ffmpeg", ["-v", "error", "-nostdin", "-y", "-ss", at, *INPUT_OPTIONS,
                   "-i", source, "-map", f"0:{video_index}", "-frames:v", "1",
                   "-vf", "scale=480:480:force_original_aspect_ratio=decrease",
                   "-q:v", "4", output], timeout=25)
    if not output.is_file() or output.stat().st_size == 0:
        raise ReelMateError("선택한 영상에서 썸네일을 읽을 수 없습니다.")


def shot_boundaries(source, asset):
    result = run("ffmpeg", ["-v", "info", "-nostdin", *INPUT_OPTIONS, "-i", source,
                           "-map", f"0:{asset['video_index']}", "-an",
                           "-vf", "scale=320:320:force_original_aspect_ratio=decrease,"
                           "select=gt(scene\\,0.32),showinfo",
                           "-f", "null", "-"], timeout=90)
    hits = sorted(float(t) for t in re.findall(rb"pts_time:([0-9.]+)", result.stderr))
    edges = [0.0]
    for hit in hits:
        if edges[-1] + 0.2 <= hit <= asset["duration"] - 0.2:
            edges.append(round(hit, 3))
    return [*edges, asset["duration"]]


def sample_frames(source, asset, directory, max_frames=36):
    count = min(max_frames, max(1, round(asset["duration"])))
    run("ffmpeg", ["-v", "error", "-nostdin", "-y", *INPUT_OPTIONS, "-i", source,
                   "-map", f"0:{asset['video_index']}", "-an",
                   "-vf", f"fps={count}/{asset['duration']},"
                   "scale=448:448:force_original_aspect_ratio=decrease",
                   "-frames:v", count, "-q:v", "4", directory / "frame-%03d.jpg"])
    paths = sorted(directory.glob("frame-*.jpg"))
    if not paths:
        raise ReelMateError("분석할 영상 프레임을 추출할 수 없습니다.")
    return paths
