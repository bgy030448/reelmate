import csv
import tempfile
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from .common import ReelMateError, json_text
from .media import run
from .renderer import render_parts, render_preview
from .validation import clip_end


ZIP_LIMIT = 80 * 1024**2
OUTPUT_FILES = {
    "preview": ("preview.mp4", "video/mp4", "mp4"),
    "package": ("editing-package.zip", "application/zip", "zip"),
    "subtitles": ("subtitles.srt", "text/plain", "srt"),
    "plan": ("edit_plan.json", "application/json", "json"),
    "report": ("brand_review.json", "application/json", "json"),
}


def timecode(sec):
    total = round(sec * 1000)
    hours, rem = divmod(total, 3_600_000)
    mins, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def srt(subtitles):
    return "".join(f"{index}\n{timecode(sub['start'])} --> {timecode(sub['end'])}\n"
                   f"{sub['text']}\n\n" for index, sub in enumerate(subtitles, 1))


def export(project, project_dir, output, validation):
    if not validation["valid"]:
        raise ReelMateError("검수 단계의 오류를 해결한 뒤 내보내세요.")
    output.mkdir()
    plan = project["plan"]
    version = plan["version"]
    assets = {asset["asset_id"]: asset for asset in project["assets"]}
    with tempfile.TemporaryDirectory(dir=output) as temp:
        work = output / temp
        parts = render_parts(project, project_dir, work)
        render_preview(plan, parts, work, output / "preview.mp4")
        edl = {**plan, "time_unit": "seconds", "project_id": project["project_id"], "sources": []}
        rows = []
        for index, clip in enumerate(plan["clips"], 1):
            name = assets[clip["asset_id"]]["filename"]
            source_id = clip["asset_id"]
            if not any(source["asset_id"] == source_id for source in edl["sources"]):
                edl["sources"].append({"asset_id": source_id, "filename": name})
            safe_name = "'" + name if name.startswith(("=", "+", "-", "@")) else name
            rows.append([f"clips/{index:03d}.mp4", clip["clip_id"], clip["segment_id"],
                         source_id, safe_name, clip["source_in"], clip["source_out"],
                         clip["timeline_start"], clip_end(clip)])
        (output / "edit_plan.json").write_text(json_text(edl), encoding="utf-8")
        report = {
            "project_id": project["project_id"], "plan_id": plan["plan_id"],
            "version": version, "time_unit": "seconds", "rules": project["rules"], **validation,
        }
        (output / "brand_review.json").write_text(json_text(report), encoding="utf-8")
        (output / "subtitles.srt").write_text(srt(plan["subtitles"]), encoding="utf-8-sig")
        with (work / "cuts.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["file", "clip_id", "segment_id", "asset_id", "source_filename",
                             "source_in_sec", "source_out_sec", "timeline_in_sec", "timeline_out_sec"])
            writer.writerows(rows)
        zip_path = output / "editing-package.zip"
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", (
                f"ReelMate 편집 패키지 · 편집안 v{version}\n\n"
                "clips의 MP4를 번호 순으로 편집기에 배치하세요. 자막은 subtitles.srt를 별도로 가져오세요.\n"
                "cuts.csv와 edit_plan.json에는 원본 구간과 최종 타임라인이 있습니다.\n"
                "이 ZIP의 가져오기 방식은 클립과 자막 개별 가져오기입니다. CapCut 프로젝트 자동 열기는 제공되지 않습니다.\n"
            ))
            archive.write(work / "cuts.csv", "cuts.csv")
            for key in ("subtitles", "plan", "report"):
                filename = OUTPUT_FILES[key][0]
                archive.write(output / filename, filename)
            clip_file = work / "clip.mp4"
            for index, part in enumerate(parts, 1):
                run("ffmpeg", ["-v", "error", "-nostdin", "-y", "-i", part, "-map", "0:v:0",
                               "-map", "0:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                               "-movflags", "+faststart", clip_file], cwd=work)
                archive.write(clip_file, f"clips/{index:03d}.mp4", compress_type=ZIP_STORED)
                if zip_path.stat().st_size > ZIP_LIMIT:
                    raise ReelMateError("편집 패키지가 80MB를 초과했습니다. 더 짧은 편집안으로 다시 시도하세요.")
        if zip_path.stat().st_size > ZIP_LIMIT:
            raise ReelMateError("편집 패키지가 80MB를 초과했습니다.")
    return {key: (output / filename).stat().st_size for key, (filename, _, _) in OUTPUT_FILES.items()}
