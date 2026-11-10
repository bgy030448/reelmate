"""Build the portable input for the Windows CapCut draft installer."""

import hashlib
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from .common import ASPECTS, FPS, ReelMateError, frames, json_text
from .exporter import ZIP_LIMIT
from .media import INPUT_OPTIONS, probe, run
from .renderer import framing_filter


CAPCUT_FILENAME = "capcut-project.zip"
CAPCUT_FORMAT = "reelmate.capcut-project.v1"


def us(frame):
    return round(frame * 1_000_000 / FPS)


def transcode_source(source, asset, output, width, height):
    # ffprobe durations are saved to milliseconds. Account for rounding at frame boundaries.
    count = math.ceil((asset["duration"] - 0.0005) * FPS)
    audio = ["-af", "aresample=48000:async=1:first_pts=0,apad"] if asset["has_audio"] else []
    run("ffmpeg", [
        "-v", "error", "-nostdin", "-y", "-filter_threads", 2, *INPUT_OPTIONS, "-i", source,
        "-map", f"0:{asset['video_index']}", "-map", "0:a:0?", "-map_metadata", "-1",
        "-vf", f"{framing_filter(width, height)},tpad=stop_mode=clone:stop_duration=0.1",
        *audio, "-t", f"{count / FPS:.9f}", "-c:v", "libx264", "-threads:v", 4,
        "-preset", "fast", "-crf", 21, "-g", FPS, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output,
    ], timeout=240)
    encoded = probe(output)
    if (frames(encoded["duration"]) != count or (encoded["width"], encoded["height"]) != (width, height)
            or encoded["has_audio"] != asset["has_audio"]):
        raise ReelMateError("CapCut용 소스의 길이, 해상도 또는 오디오가 원본과 맞지 않습니다.")
    return count


def export_capcut(project, project_dir, output):
    plan = project["plan"]
    width, height = ASPECTS[plan["aspect_ratio"]]
    assets = {asset["asset_id"]: asset for asset in project["assets"]}
    asset_ids = dict.fromkeys(clip["asset_id"] for clip in plan["clips"])

    manifest = {
        "format": CAPCUT_FORMAT, "plan_version": plan["version"],
        "fps": FPS, "width": width, "height": height,
        "duration": frames(plan["actual_duration"]),
        "sources": [], "clips": [], "subtitles": [],
    }
    output.mkdir()
    bundle = output / CAPCUT_FILENAME
    with TemporaryDirectory(dir=output) as temp, ZipFile(bundle, "w", ZIP_DEFLATED) as archive:
        source_ids = {}
        size = 0
        for index, asset_id in enumerate(asset_ids, 1):
            asset = assets[asset_id]
            source_ids[asset_id] = index
            filename = f"source-{index:03d}.mp4"
            encoded = Path(temp) / filename
            duration = transcode_source(project_dir / asset["path"], asset, encoded, width, height)
            encoded_size = encoded.stat().st_size
            size += encoded_size
            if size > ZIP_LIMIT:
                raise ReelMateError("CapCut 프로젝트의 전체 소스가 80MB를 초과했습니다. 사용 원본 수나 길이를 줄여 주세요.")
            with encoded.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            archive.write(encoded, f"media/{filename}", compress_type=ZIP_STORED)
            manifest["sources"].append({
                "name": asset["filename"], "frames": duration, "has_audio": asset["has_audio"],
                "sha256": digest, "bytes": encoded_size,
            })
            encoded.unlink()
        for clip in plan["clips"]:
            source = source_ids[clip["asset_id"]]
            length = frames(clip["source_out"] - clip["source_in"])
            last_in = manifest["sources"][source - 1]["frames"] - length
            manifest["clips"].append({
                "source": source,
                "in": min(frames(clip["source_in"]), last_in),
                "at": frames(clip["timeline_start"]),
                "frames": length,
            })
        for sub in plan["subtitles"]:
            manifest["subtitles"].append({
                "text": sub["text"], "start": frames(sub["start"]), "end": frames(sub["end"]),
                "position": sub["style"]["position"],
            })
        serialized = json_text(manifest).encode("utf-8")
        readme = (
            f"ReelMate CapCut 프로젝트 패키지 · 편집안 v{plan['version']}\n\n"
            "ReelMate의 Windows 설치 도구로 CapCut에서 만든 ReelMate Test 전용 초안에 적용합니다.\n"
            "CapCut을 완전히 종료하고 reelmate.capcut_install의 미리보기 검사부터 실행하세요.\n"
            "명령과 샘플 조건은 ReelMate의 docs/capcut-validation.md를 확인하세요.\n"
            "영상 소스에는 자막이 합성되지 않았습니다. 자막은 별도 CapCut 텍스트 객체로 생성됩니다.\n"
        ).encode("utf-8")
        if size + len(serialized) + len(readme) > ZIP_LIMIT:
            raise ReelMateError("CapCut 프로젝트 ZIP이 80MB를 초과했습니다.")
        archive.writestr("manifest.json", serialized)
        archive.writestr("README.txt", readme)
    if bundle.stat().st_size > ZIP_LIMIT:
        raise ReelMateError("CapCut 프로젝트 ZIP이 80MB를 초과했습니다.")
    return bundle.stat().st_size
