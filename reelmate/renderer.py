import os
import shutil
from pathlib import Path

from PIL import ImageFont

from .common import ASPECTS, FPS, ReelMateError, frames
from .media import INPUT_OPTIONS, run


def korean_font():
    override = os.getenv("REELMATE_FONT")
    candidates = [Path(override)] if override else [
        Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "malgunbd.ttf",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ReelMateError("한글 자막용 폰트를 찾을 수 없습니다. REELMATE_FONT를 설정하세요.")


def clip_seconds(clip):
    return frames(clip["source_out"] - clip["source_in"]) / FPS


def framing_filter(width, height):
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2,"
            f"crop={width}:{height},setsar=1,fps={FPS}")


def render_parts(project, directory, work):
    plan = project["plan"]
    width, height = ASPECTS[plan["aspect_ratio"]]
    assets = {asset["asset_id"]: asset for asset in project["assets"]}
    parts = []
    (work / "parts").mkdir()
    for index, clip in enumerate(plan["clips"], 1):
        asset = assets[clip["asset_id"]]
        target = f"parts/{index:03d}.mkv"
        length = clip_seconds(clip)
        command = ["-v", "error", "-nostdin", "-y", "-filter_threads", 2,
                   "-ss", clip["source_in"], *INPUT_OPTIONS, "-i", directory / asset["path"]]
        if not asset["has_audio"]:
            command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
        audio = "0:a:0" if asset["has_audio"] else "1:a:0"
        run("ffmpeg", [
            *command, "-map", f"0:{asset['video_index']}", "-map", audio,
            "-vf", f"{framing_filter(width, height)},tpad=stop_mode=clone:stop_duration={length:.9f}",
            "-af", "aresample=48000:async=1:first_pts=0,apad",
            "-t", f"{length:.9f}", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-threads:v", 4,
            "-preset", "fast", "-crf", 19, "-c:a", "pcm_s16le", "-ac", 2,
            "-map_metadata", "-1", target,
        ], cwd=work)
        parts.append(target)
    return parts


def wrap_caption(text, font, max_width):
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for char in paragraph:
            if line and font.getlength(line + char) > max_width:
                lines.append(line.rstrip())
                line = ""
            line += char
        lines.append(line.strip())
    return "\n".join(lines)


def render_preview(plan, parts, work, output):
    concat = "".join(f"file '{part}'\nduration {clip_seconds(clip):.9f}\n"
                     for part, clip in zip(parts, plan["clips"], strict=True))
    (work / "timeline.ffconcat").write_text(concat, encoding="ascii")
    filters = [f"setpts=N/({FPS}*TB)"]
    if plan["subtitles"]:
        font_path = korean_font()
        width, height = ASPECTS[plan["aspect_ratio"]]
        font_size = max(26, round(min(width, height) * 0.057))
        font = ImageFont.truetype(str(font_path), font_size)
        shutil.copyfile(font_path, work / "caption-font.ttf")
        for index, subtitle in enumerate(plan["subtitles"], 1):
            text_file = f"caption-{index:03d}.txt"
            caption = wrap_caption(subtitle["text"], font, width * 0.86)
            if (caption.count("\n") + 1) * (font_size + 6) > height * 0.68:
                raise ReelMateError("자막이 화면에 들어가지 않습니다. 여러 자막으로 나누거나 줄을 줄이세요.")
            (work / text_file).write_text(caption, encoding="utf-8")
            y = {
                "top": "h*0.10",
                "middle": "(h-th)/2",
                "bottom": "h-th-h*0.11",
            }[subtitle["style"]["position"]]
            start, end = frames(subtitle["start"]), frames(subtitle["end"])
            filters.append(
                f"drawtext=fontfile=caption-font.ttf:textfile={text_file}:expansion=none:"
                f"fontsize={font_size}:fontcolor=white:line_spacing=6:borderw=2:bordercolor=black:"
                f"box=1:boxcolor=black@0.55:boxborderw=8:x=(w-tw)/2:y={y}:"
                f"enable='gte(n,{start})*lt(n,{end})'"
            )
    run("ffmpeg", [
        "-v", "error", "-nostdin", "-y", "-filter_threads", 2, "-f", "concat", "-safe", 1,
        "-i", "timeline.ffconcat", "-vf", ",".join(filters),
        "-af", "aresample=48000:async=1:first_pts=0,apad",
        "-t", f"{frames(plan['actual_duration']) / FPS:.9f}", "-c:v", "libx264", "-threads:v", 4,
        "-preset", "fast", "-crf", 21, "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", output,
    ], cwd=work, timeout=240)
