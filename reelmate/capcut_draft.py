"""Adapt an app-created Windows CapCut test draft without replacing its identity."""

import json
import re
from copy import deepcopy
from pathlib import Path
from time import time_ns
from uuid import UUID, uuid4

from .capcut import us
from .common import FPS, ReelMateError, json_text, record


DRAFT_NAMES = ("draft_content.json", "draft_info.json")
BACKUP_NAMES = tuple(f"{name}.bak" for name in DRAFT_NAMES)
MIRROR_NAMES = ("template-2.tmp", "template.tmp")
TEST_NAME = "ReelMate Test"
READ_LIMIT = 5 * 1024**2
DEFAULT_REFS = {
    "speeds", "placeholder_infos", "canvases", "sound_channel_mappings",
    "material_colors", "vocal_separations", "material_animations",
}
TEXT_Y = {"top": 0.73, "middle": 0.0, "bottom": -0.72}


def draft_id():
    return str(uuid4()).upper()


def identity(value):
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReelMateError("CapCut 초안의 프로젝트 또는 타임라인 ID를 읽을 수 없습니다.") from exc


def plain_object(raw, name):
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ReelMateError(f"{name}에 평문 JSON이 필요합니다. 해당 CapCut 저장 형식은 아직 지원하지 않습니다.") from exc
    return record(result, name)


def read_sample(path, snapshots, optional=False):
    if path.is_symlink() or path.resolve() != path:
        raise ReelMateError("링크를 거치지 않는 실제 CapCut 초안 폴더를 선택하세요.")
    if optional and not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > READ_LIMIT:
        raise ReelMateError(f"{path.name} 파일이 없거나 검사 한도인 5MB를 초과합니다.")
    with path.open("rb") as handle:
        raw = handle.read(READ_LIMIT + 1)
    if len(raw) > READ_LIMIT:
        raise ReelMateError(f"{path.name} 파일이 검사 한도인 5MB를 초과합니다.")
    if optional and not raw.strip() and path.name in MIRROR_NAMES:
        return None
    value = plain_object(raw, path.name)
    snapshots[path] = raw
    return value


def validate_build(doc, build):
    platform = record(doc.get("platform"), "CapCut 플랫폼")
    reported = platform.get("app_version", "")
    if platform.get("app_source") != "cc" or str(platform.get("os")).lower() != "windows":
        raise ReelMateError("CapCut Desktop에서 Windows 로컬 초안을 생성하세요.")
    if not isinstance(reported, str) or reported not in {build, build.rsplit(".", 1)[0]}:
        raise ReelMateError("입력한 CapCut 빌드와 초안의 앱 버전이 다릅니다. 같은 버전에서 초안을 새로 만드세요.")
    schema = doc.get("new_version")
    if not isinstance(schema, str) or not re.fullmatch(r"\d+\.\d+\.\d+", schema):
        raise ReelMateError("CapCut 초안의 스키마 버전을 확인할 수 없습니다.")


def load_draft(folder, build):
    if not re.fullmatch(r"9\.\d+\.\d+\.\d+", build):
        raise ReelMateError("Windows CapCut Desktop 9.x의 전체 빌드 번호를 입력하세요. 예시는 9.3.0.3970입니다.")
    snapshots = {}
    meta_path = folder / "draft_meta_info.json"
    meta = read_sample(meta_path, snapshots)
    identity(meta.get("draft_id"))
    registered_path = meta.get("draft_fold_path")
    if registered_path and (not isinstance(registered_path, str) or Path(registered_path).resolve() != folder):
        raise ReelMateError("CapCut에서 이 시험용 초안이 저장된 실제 폴더를 지정하세요.")
    if meta.get("cloud_draft_sync") or meta.get("draft_is_cloud_temp_draft"):
        raise ReelMateError("CapCut 클라우드 동기화를 사용하지 않는 시험용 로컬 초안을 선택하세요.")
    name = meta.get("draft_name", "")
    if not isinstance(name, str) or not (name == TEST_NAME or name.startswith(TEST_NAME + " - ")):
        raise ReelMateError(f"CapCut에서 새 프로젝트를 만들고 이름을 '{TEST_NAME}'으로 지정하세요.")
    roots = {}
    for filename in DRAFT_NAMES:
        path = folder / filename
        value = read_sample(path, snapshots, optional=True)
        if value is not None:
            roots[path] = value
    if not roots:
        raise ReelMateError("CapCut 시험용 초안에 draft_content.json 또는 draft_info.json이 필요합니다.")

    canonical = next(iter(roots.values()))
    selected = identity(canonical.get("id"))
    index = read_sample(folder / "Timelines" / "project.json", snapshots, optional=True)
    active_folder = None
    if index is not None:
        timeline = index.get("main_timeline_id")
        entries = index.get("timelines")
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            raise ReelMateError("시험용 초안에는 타임라인을 하나만 두세요.")
        if (identity(entries[0].get("id")) != selected or identity(timeline) != selected
                or entries[0].get("is_marked_delete")):
            raise ReelMateError("루트 초안과 활성 타임라인이 일치하지 않습니다.")
        active_folder = folder / "Timelines" / timeline
        active_docs = {}
        for filename in DRAFT_NAMES:
            path = active_folder / filename
            value = read_sample(path, snapshots, optional=True)
            if value is not None:
                active_docs[path] = value
        if not active_docs:
            raise ReelMateError("CapCut이 저장한 활성 타임라인 파일을 찾지 못했습니다.")
        roots.update(active_docs)
        canonical = next(iter(active_docs.values()))
    elif (folder / "Timelines").exists():
        raise ReelMateError("활성 타임라인을 확인할 Timelines/project.json이 필요합니다.")

    validate_build(canonical, build)
    for base in [folder] + ([active_folder] if active_folder else []):
        for filename in (*MIRROR_NAMES, *BACKUP_NAMES):
            path = base / filename
            value = read_sample(path, snapshots, optional=True)
            if value is not None:
                roots[path] = value

    fields = ("tracks", "materials", "canvas_config", "duration", "new_version")
    for path, doc in roots.items():
        if identity(doc.get("id")) != selected:
            raise ReelMateError("CapCut 초안 복사본의 타임라인 ID가 다릅니다. 시험용 초안을 새로 저장하세요.")
        if path.name not in BACKUP_NAMES and any(doc.get(key) != canonical.get(key) for key in fields):
            raise ReelMateError("CapCut 초안 복사본이 서로 다릅니다. 앱에서 다시 저장하고 종료한 뒤 검사하세요.")

    virtual_path = folder / "draft_virtual_store.json"
    virtual = read_sample(virtual_path, snapshots, optional=True)
    return canonical, meta, virtual, tuple(roots), snapshots


def timerange(start, end):
    return {"start": us(start), "duration": us(end) - us(start)}


def sample_tracks(document):
    tracks = document.get("tracks")
    if not isinstance(tracks, list) or [record(t, "트랙").get("type") for t in tracks] != ["video", "text"]:
        raise ReelMateError("CapCut 시험용 타임라인에 메인 영상 트랙 하나와 기본 텍스트 트랙 하나만 두세요.")
    video, text = tracks
    for track in tracks:
        segments = track.get("segments")
        if track.get("flag", 0) != 0 or track.get("attribute", 0) != 0 or not isinstance(segments, list) or len(segments) != 2:
            raise ReelMateError("시험용 메인 트랙에 컷 2개, 기본 텍스트 트랙에 자막 2개를 배치하세요.")
        for segment in segments:
            segment = record(segment, "CapCut 구간")
            if (segment.get("speed", 1) != 1 or segment.get("common_keyframes")
                    or segment.get("keyframe_refs") or segment.get("group_id")):
                raise ReelMateError("속도 변경, 키프레임, 그룹이 없는 기본 시험용 초안을 준비하세요.")
    return video, text


def material_pool(document):
    groups = record(document.get("materials"), "CapCut 자료")
    pool = {}
    for key, entries in groups.items():
        if entries is None:
            continue
        if not isinstance(entries, list) or (entries and key not in DEFAULT_REFS | {"videos", "texts"}):
            raise ReelMateError("시험용 초안에서 효과, 전환, 스티커, 별도 오디오를 제거하세요.")
        for row in entries:
            row = record(row, "CapCut 자료")
            material = identity(row.get("id"))
            if material in pool:
                raise ReelMateError("CapCut 초안에 중복 자료 ID가 있습니다.")
            pool[material] = (key, row)
    return groups, pool


def get_material(pool, ref, kind):
    entry = pool.get(identity(ref))
    if entry is None or entry[0] != kind:
        raise ReelMateError("CapCut 시험용 초안에 영상 또는 텍스트의 자료 참조가 없습니다.")
    return entry[1]


def clone_segment(template, pool, materials, material_id, target, source, track, y):
    segment = deepcopy(template)
    clip = record(segment.get("clip"), "CapCut 구간 변환")
    clip.update(transform={"x": 0.0, "y": y}, scale={"x": 1.0, "y": 1.0}, rotation=0.0,
                flip={"horizontal": False, "vertical": False}, alpha=1.0)
    refs = segment.get("extra_material_refs", [])
    if not isinstance(refs, list):
        raise ReelMateError("CapCut 구간의 추가 자료 참조가 올바르지 않습니다.")
    extra = []
    for key in refs:
        kind, prototype = pool.get(identity(key), (None, None))
        if (kind not in DEFAULT_REFS
                or prototype.get("animations") or prototype.get("curve_speed")
                or (kind == "canvases" and (prototype.get("image") or prototype.get("blur")))):
            raise ReelMateError("효과나 애니메이션이 없는 기본 시험용 초안이 필요합니다.")
        resource = deepcopy(prototype)
        resource["id"] = draft_id()
        materials[kind].append(resource)
        extra.append(resource["id"])
    segment.update(id=draft_id(), material_id=material_id, target_timerange=target,
                   source_timerange=source, extra_material_refs=extra, speed=1.0,
                   track_render_index=track, group_id="", visible=True)
    if segment.get("render_timerange") is not None:
        segment["render_timerange"] = {"start": 0, "duration": 0}
    return segment


def replace_text(material, text):
    material = deepcopy(material)
    material["id"] = draft_id()
    for key in ("content", "base_content"):
        value = material.get(key)
        if not value and key == "base_content":
            continue
        if not isinstance(value, str):
            raise ReelMateError("CapCut 기본 텍스트에 편집 가능한 내용이 없습니다.")
        model = plain_object(value, "CapCut 텍스트")
        styles = model.get("styles")
        if not isinstance(styles, list) or len(styles) != 1 or not isinstance(styles[0], dict):
            raise ReelMateError("시험용 자막은 서식 한 가지를 적용한 기본 텍스트를 사용하세요.")
        model["text"] = text
        styles[0]["range"] = [0, len(text.encode("utf-16-le")) // 2]
        material[key] = json_text(model).strip()
    if "text" in material:
        material["text"] = text
    return material


def compile_draft(document, meta, virtual, manifest, media_dir):
    document, meta, virtual = deepcopy(document), deepcopy(meta), deepcopy(virtual)
    video_track, text_track = sample_tracks(document)
    groups, pool = material_pool(document)
    video_template, text_template = video_track["segments"][0], text_track["segments"][0]
    video_material = get_material(pool, video_template.get("material_id"), "videos")
    text_material = get_material(pool, text_template.get("material_id"), "texts")
    if video_material.get("type") != "video" or text_material.get("type") != "text":
        raise ReelMateError("시험용 초안에는 로컬 영상과 '기본 텍스트'를 사용하세요.")
    # Validate the second pair as well, to keep this writer limited to simple test drafts.
    if (get_material(pool, video_track["segments"][1].get("material_id"), "videos").get("type") != "video"
            or get_material(pool, text_track["segments"][1].get("material_id"), "texts").get("type") != "text"):
        raise ReelMateError("시험용 초안에는 로컬 영상 두 개와 기본 텍스트 두 개가 필요합니다.")
    width, height = manifest["width"], manifest["height"]
    ratio = {(540, 960): "9:16", (960, 540): "16:9", (720, 720): "1:1"}[(width, height)]
    record(document.get("canvas_config"), "CapCut 캔버스").update(width=width, height=height, ratio=ratio)
    document.update(fps=float(FPS), duration=us(manifest["duration"]))
    materials = {key: [] if isinstance(value, list) else value for key, value in groups.items()}
    video_track["segments"] = []
    text_track["segments"] = []
    document["materials"] = materials

    buckets = meta.get("draft_materials")
    if not isinstance(buckets, list):
        raise ReelMateError("CapCut 미디어 보관함을 읽을 수 없습니다.")
    rows = [record(bucket, "CapCut 보관함") for bucket in buckets]
    video_bucket = next((bucket for bucket in rows if bucket.get("type") == 0), None)
    original_bin = video_bucket.get("value") if video_bucket else None
    if not isinstance(original_bin, list) or not original_bin:
        raise ReelMateError("CapCut에서 시험용 영상을 미디어 보관함에 먼저 가져오세요.")
    bin_rows = [record(row, "CapCut 미디어 보관함 자료") for row in original_bin]
    prototype = next((row for row in bin_rows if row.get("metetype") == "video" and row.get("file_Path")), None)
    if not prototype or any(row.get("metetype") not in {"none", "video"} for row in bin_rows):
        raise ReelMateError("시험용 초안의 미디어 보관함에 로컬 영상 두 개를 가져오세요.")
    video_bucket["value"] = [row for row in bin_rows if row.get("metetype") == "none"]
    if any(bucket.get("value") for bucket in rows if bucket is not video_bucket):
        raise ReelMateError("시험용 초안의 미디어 보관함에는 로컬 영상만 남겨 주세요.")

    stamp = time_ns() // 1000
    asset_pairs = []
    for index, source in enumerate(manifest["sources"], 1):
        asset_id = draft_id()
        path = (media_dir / f"source-{index:03d}.mp4").as_posix()
        asset = deepcopy(prototype)
        asset.update(id=asset_id, file_Path=path, extra_info=source["name"], metetype="video",
                     width=width, height=height, duration=us(source["frames"]),
                     roughcut_time_range=timerange(0, source["frames"]), md5="",
                     import_time=stamp // 1_000_000, import_time_ms=stamp)
        video_bucket["value"].append(asset)
        asset_pairs.append((asset, source))

    for item in manifest["clips"]:
        asset, source = asset_pairs[item["source"] - 1]
        video = deepcopy(video_material)
        video.update(id=draft_id(), local_material_id=asset["id"], path=asset["file_Path"],
                     material_name=source["name"], duration=asset["duration"], width=width, height=height,
                     has_audio=source["has_audio"], crop_ratio="free", crop_scale=1.0,
                     crop={"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0,
                           "upper_right_y": 0.0, "lower_left_x": 0.0, "lower_left_y": 1.0,
                           "lower_right_x": 1.0, "lower_right_y": 1.0})
        for key in ("media_path", "material_url", "reverse_path"):
            if key in video:
                video[key] = ""
        materials["videos"].append(video)
        segment = clone_segment(video_template, pool, materials, video["id"],
                                timerange(item["at"], item["at"] + item["frames"]),
                                timerange(item["in"], item["in"] + item["frames"]), 0, 0.0)
        segment.update(volume=1.0, last_nonzero_volume=1.0, render_index=0)
        video_track["segments"].append(segment)

    for index, item in enumerate(manifest["subtitles"]):
        material = replace_text(text_material, item["text"])
        materials["texts"].append(material)
        segment = clone_segment(text_template, pool, materials, material["id"],
                                timerange(item["start"], item["end"]), None, 1, TEXT_Y[item["position"]])
        segment["render_index"] = 14000 + index
        text_track["segments"].append(segment)
    if not text_track["segments"]:
        document["tracks"] = [video_track]

    meta.update(tm_duration=document["duration"], tm_draft_modified=stamp)
    if "draft_timeline_materials_size_" in meta:
        meta["draft_timeline_materials_size_"] = sum(source["bytes"] for source in manifest["sources"])
    if virtual is not None:
        data = virtual.get("draft_virtual_store")
        if not isinstance(data, list):
            raise ReelMateError("CapCut 가상 보관함의 형식이 이 버전과 맞지 않습니다.")
        links = next((record(group, "CapCut 가상 보관함") for group in data
                      if isinstance(group, dict) and group.get("type") == 1), None)
        if links is None:
            raise ReelMateError("CapCut 가상 보관함의 미디어 그룹을 찾을 수 없습니다.")
        links["value"] = [{"child_id": asset["id"], "parent_id": ""} for asset, _ in asset_pairs]
    return document, meta, virtual
