import json
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

import pytest

from reelmate import capcut_install
from reelmate.capcut import CAPCUT_FILENAME
from reelmate.capcut_draft import draft_id
from reelmate.common import ReelMateError, atomic_json
from reelmate.media import probe


BUILD = "9.3.0.3970"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def exported(project, media_samples):
    project.upload(media_samples[:2])
    project.do("plan_save", clips=project.two_cuts(), subtitles=[
        {"text": "제품 소개 🎬", "start": 1, "end": 3, "style": {"position": "top"}},
        {"text": "사용 장면", "start": 6, "end": 8, "style": {"position": "bottom"}},
    ])
    result = project.do("capcut_export")
    entry = project.data["capcut_exports"][0]
    assert entry["version"] == result["capcut_version"] == project.data["plan"]["version"]
    return project.directory / entry["directory"] / CAPCUT_FILENAME


@pytest.fixture
def sample(tmp_path, monkeypatch):
    """Synthetic plain JSON for a simple CapCut-authored Windows 9.x layout."""
    monkeypatch.setattr(capcut_install, "capcut_running", lambda: False)
    root = tmp_path / "drafts"
    folder = root / "ReelMate Test"
    timeline = draft_id()
    identity = draft_id()
    nested = folder / "Timelines" / timeline
    videos = [{"id": draft_id(), "type": "video", "path": f"C:/fixture/clip-{i}.mp4"} for i in (1, 2)]
    texts = [{"id": draft_id(), "type": "text", "content": json.dumps({
        "text": "샘플 텍스트", "styles": [{"size": 15, "range": [0, 6]}],
    })} for _ in range(2)]
    speed = {"id": draft_id(), "type": "speed", "speed": 1, "curve_speed": None}
    tracks = []
    for track_type, materials in [("video", videos), ("text", texts)]:
        tracks.append({
            "id": draft_id(), "type": track_type, "flag": 0, "attribute": 0,
            "segments": [{
                "id": draft_id(), "material_id": material["id"], "clip": {},
                "extra_material_refs": [speed["id"]] if track_type == "video" else [],
                "target_timerange": {"start": index * 5_000_000, "duration": 5_000_000},
                "source_timerange": {"start": 0, "duration": 5_000_000} if track_type == "video" else None,
            } for index, material in enumerate(materials)],
        })
    document = {
        "id": timeline, "version": 360000, "new_version": "181.0.0",
        "platform": {"app_source": "cc", "os": "windows", "app_version": "9.3.0"},
        "canvas_config": {"width": 1080, "height": 1920, "ratio": "9:16"},
        "fps": 30, "duration": 10_000_000, "tracks": tracks,
        "materials": {"videos": videos, "texts": texts, "speeds": [speed], "transitions": []},
    }
    media_bin = [{"id": draft_id(), "metetype": "none", "file_Path": ""}] + [
        {"id": draft_id(), "metetype": "video", "file_Path": row["path"]} for row in videos
    ]
    meta = {
        "draft_id": identity, "draft_name": "ReelMate Test", "draft_fold_path": folder.as_posix(),
        "draft_timeline_materials_size_": 300, "tm_duration": 10_000_000,
        "draft_materials": [{"type": 0, "value": media_bin}, {"type": 1, "value": []}],
    }
    index = {"id": identity, "main_timeline_id": timeline, "timelines": [{"id": timeline}], "version": 0}
    atomic_json(root / "root_meta_info.json", {"all_draft_store": [{"draft_id": identity}]})
    atomic_json(folder / "Timelines" / "project.json", index)
    for path in (folder / "draft_content.json", nested / "draft_content.json", folder / "template-2.tmp",
                 nested / "template-2.tmp", nested / "draft_content.json.bak"):
        atomic_json(path, document)
    atomic_json(folder / "draft_meta_info.json", meta)
    atomic_json(folder / "draft_virtual_store.json", {"draft_virtual_store": [
        {"type": 0, "value": []},
        {"type": 1, "value": [{"child_id": row["id"], "parent_id": ""} for row in media_bin[1:]]},
    ]})
    return folder


def snapshots(folder):
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*") if path.is_file()}


def test_package_preserves_full_sources_and_output_versions(project, exported, tmp_path):
    plan = project.data["plan"]
    assert not project.data["outputs"]
    with ZipFile(exported) as archive:
        manifest = capcut_install.read_package(archive)
        capcut_install.verify_media(archive, manifest, tmp_path)
    assert manifest["duration"] == 300
    assert manifest["clips"] == [
        {"source": 1, "in": 15, "at": 0, "frames": 150},
        {"source": 2, "in": 15, "at": 150, "frames": 150},
    ]
    assert manifest["subtitles"][0]["text"] == "제품 소개 🎬"
    assert "C:\\" not in json.dumps(manifest, ensure_ascii=False)
    for index, has_audio in [(1, True), (2, False)]:
        asset = probe(tmp_path / f"source-{index:03d}.mp4")
        assert (asset["duration"], asset["fps"], asset["codec"], asset["has_audio"]) == (6, 30, "h264", has_audio)
    record = project.data["capcut_exports"][0]
    project.do("capcut_export")
    assert project.data["capcut_exports"] == [record]
    assert project.do("export")["output_version"] == record["version"]
    project.do("plan_save", clips=plan["clips"], subtitles=plan["subtitles"][:1])
    project.do("capcut_export")
    assert len(project.data["capcut_exports"]) == 2 and exported.is_file()


def test_install_keeps_project_and_updates_root_and_active_timeline(exported, sample, tmp_path):
    before = snapshots(sample)
    registry = sample.parent / "root_meta_info.json"
    registry_before = registry.read_bytes()
    backups = tmp_path / "backups"
    checked = capcut_install.install(exported, sample, BUILD, backup_root=backups)
    assert checked["clips"] == checked["subtitles"] == 2
    assert checked["backup"] is None and snapshots(sample) == before and not backups.exists()
    applied = capcut_install.install(exported, sample, BUILD, apply=True, backup_root=backups)
    saved = read_json(sample / "draft_content.json")
    assert saved["id"] == json.loads(before["draft_content.json"])["id"]
    assert registry.read_bytes() == registry_before
    assert (sample / "Timelines" / "project.json").read_bytes() == before["Timelines/project.json"]
    for file in applied["files"]:
        assert (applied["backup"] / file).read_bytes() == before[file]
        if Path(file).name != "draft_meta_info.json" and Path(file).name != "draft_virtual_store.json":
            assert read_json(sample / file) == saved
    video, text = saved["tracks"]
    assert (video["type"], text["type"]) == ("video", "text")
    assert saved["duration"] == 10_000_000
    assert [segment["target_timerange"]["start"] for segment in video["segments"]] == [0, 5_000_000]
    assert video["segments"][0]["source_timerange"] == {"start": 500_000, "duration": 5_000_000}
    assert text["segments"][0]["source_timerange"] is None
    assert text["segments"][0]["target_timerange"] == {"start": 1_000_000, "duration": 2_000_000}
    assert text["segments"][0]["clip"]["transform"]["y"] > 0 > text["segments"][1]["clip"]["transform"]["y"]
    texts = [json.loads(row["content"]) for row in saved["materials"]["texts"]]
    assert texts[0]["text"] == "제품 소개 🎬"
    assert texts[0]["styles"][0]["range"] == [0, len(texts[0]["text"].encode("utf-16-le")) // 2]
    meta = read_json(sample / "draft_meta_info.json")
    assert meta["draft_id"] == json.loads(before["draft_meta_info.json"])["draft_id"]
    assets = {row["id"]: row for row in meta["draft_materials"][0]["value"]}
    for item in saved["materials"]["videos"]:
        assert item["duration"] == 6_000_000
        assert Path(item["path"]).is_file()
        assert assets[item["local_material_id"]]["file_Path"] == item["path"]
    assert len({seg["id"] for track in saved["tracks"] for seg in track["segments"]}) == 4
    with pytest.raises(ReelMateError, match="이미 사용"):
        capcut_install.install(exported, sample, BUILD, apply=True, backup_root=backups)


def test_refuses_incompatible_build_or_non_test_draft(exported, sample):
    with pytest.raises(ReelMateError, match="9.x"):
        capcut_install.install(exported, sample, "10.0.0.4100")
    with pytest.raises(ReelMateError, match="버전이 다릅니다"):
        capcut_install.install(exported, sample, "9.5.0.4050")
    meta = read_json(sample / "draft_meta_info.json")
    meta["draft_name"] = "실제 작업 중인 프로젝트"
    atomic_json(sample / "draft_meta_info.json", meta)
    before = snapshots(sample)
    with pytest.raises(ReelMateError, match="ReelMate Test"):
        capcut_install.install(exported, sample, BUILD, apply=True)
    assert snapshots(sample) == before


def test_refuses_locked_divergent_and_encoded_drafts(exported, sample):
    lock = sample / ".locked"
    lock.touch()
    with pytest.raises(ReelMateError, match="완전히 종료"):
        capcut_install.install(exported, sample, BUILD)
    lock.unlink()
    mirror = sample / "template-2.tmp"
    document = read_json(mirror)
    atomic_json(mirror, document | {"duration": 9_000_000})
    with pytest.raises(ReelMateError, match="복사본이 서로 다릅니다"):
        capcut_install.install(exported, sample, BUILD)
    mirror.write_bytes(b"Opaque draft")
    with pytest.raises(ReelMateError, match="평문 JSON"):
        capcut_install.install(exported, sample, BUILD)


def test_install_rolls_back_if_a_native_write_fails(exported, sample, tmp_path, monkeypatch):
    before = snapshots(sample)
    def fail_meta(path, value):
        if path == sample / "draft_meta_info.json":
            raise OSError("simulated write error")
        atomic_json(path, value)
    monkeypatch.setattr(capcut_install, "atomic_json", fail_meta)
    with pytest.raises(OSError, match="simulated write error"):
        capcut_install.install(exported, sample, BUILD, apply=True, backup_root=tmp_path / "backup")
    assert snapshots(sample) == before
    assert not (sample / "reelmate-media-v1").exists()


def test_installer_rejects_zip_paths_and_inconsistent_timing(exported, sample, tmp_path):
    archive_path = tmp_path / "invalid.zip"
    with ZipFile(exported) as original:
        manifest = json.loads(original.read("manifest.json"))
        media = {name: original.read(name) for name in original.namelist() if name != "manifest.json"}
    with ZipFile(archive_path, "w") as zip_file:
        zip_file.writestr("manifest.json", json.dumps(manifest))
        for name, value in media.items():
            zip_file.writestr(name, value)
        zip_file.writestr("../should-not-exist", b"attack")
    with pytest.raises(ReelMateError, match="파일 목록"):
        capcut_install.install(archive_path, sample, BUILD)
    with ZipFile(archive_path, "w") as zip_file:
        bad = deepcopy(manifest)
        bad["clips"][1]["at"] += 1
        zip_file.writestr("manifest.json", json.dumps(bad))
        for name, value in media.items():
            zip_file.writestr(name, value)
    with pytest.raises(ReelMateError, match="타임라인이 겹치거나"):
        capcut_install.install(archive_path, sample, BUILD)


def test_capcut_export_obeys_brand_review(project, media_samples):
    project.upload(media_samples[:2])
    project.do("guide_text", text="브랜드 가이드 승인 필요")
    project.do("plan_save", clips=project.two_cuts(), subtitles=[])
    before = project.data
    with pytest.raises(ReelMateError, match="규칙 목록을 승인하세요"):
        project.do("capcut_export")
    assert project.data == before
