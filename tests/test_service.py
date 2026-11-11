import json
from zipfile import ZipFile

import pytest

from reelmate.common import ReelMateError
from reelmate.media import probe, run
from reelmate.service import Service
from reelmate.validation import validate
from conftest import encoded


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1, True, "10", 61])
def test_reject_invalid_target(project, duration):
    with pytest.raises(ReelMateError, match="목표 길이"):
        project.do("project_settings", **(project.settings | {"target_duration": duration}))


def test_reload_and_stale_revision(project):
    initial = project.data
    project.do("project_settings", **(project.settings | {"brand": "새 브랜드"}))
    with pytest.raises(ReelMateError, match="다른 창"):
        project.service.dispatch("project_settings", project.settings, project.id, initial["revision"])
    reopened = Service(project.service.root)
    assert reopened.project(project.id)["brand"] == "새 브랜드"
    assert reopened.projects()[0]["project_id"] == project.id


def test_upload_failure_preserves_prior_files(project, media_samples, tmp_path):
    project.upload(media_samples[:1])
    before = project.data
    files = sorted(p.relative_to(project.directory) for p in project.directory.rglob("*") if p.is_file())
    invalid = tmp_path / "broken.mp4"
    invalid.write_bytes(b"invalid mp4")
    with pytest.raises(ReelMateError, match="broken.mp4"):
        project.upload([media_samples[1], invalid])
    with pytest.raises(ReelMateError, match="파일명"):
        project.do("upload", role="source", files=[encoded(media_samples[1], "../outside.mp4")])
    assert project.data == before
    assert sorted(p.relative_to(project.directory) for p in project.directory.rglob("*") if p.is_file()) == files


@pytest.mark.parametrize("reference_count", [1, 3])
def test_reference_only_style_measurement_and_roundtrip(project, media_samples, tmp_path, reference_count):
    project.upload(media_samples[:reference_count], role="reference")
    assert project.data["segments"] == []
    project.do("style_measure", clip=False, ocr=False)
    draft = project.data["style_draft"]
    assert len(draft["evidence"]) == reference_count
    assert draft["avg_shot_length"] == 6
    approved = project.do("profile_save", **(draft | {"name": "제품 소개 스타일", "approve": True,
                            "observations": [{"asset_id": draft["evidence"][0]["asset_id"],
                                              "opening": "제품 소개", "first_product_sec": 1.2}]}))
    profile = project.service.profile(approved["profile_id"])
    assert profile["approved_at"]
    assert profile["evidence"][0]["manual"]["first_product_sec"] == 1.2
    second = Service(tmp_path / "second")
    result = second.dispatch("profile_import", profile)
    loaded = second.profile(result["profile_id"])
    assert loaded["name"] == profile["name"]
    assert loaded["evidence"][0]["manual"] == profile["evidence"][0]["manual"]
    assert not loaded["approved_at"]
    assert set(p["role"] for p in project.data["assets"]) == {"reference"}


def test_rules_check_evidence_and_clear_on_edit(project, media_samples):
    project.upload(media_samples[:2])
    project.do("guide_text", text="첫 제품 소개와 브랜드 문구, 로고 확인이 필요합니다.")
    project.do("rules_save", rules=[
        {"type": "product_deadline", "value": "product", "deadline_sec": 2},
        {"type": "required_text", "value": "광고"},
        {"type": "manual", "value": "로고가 정확합니다."},
    ])
    project.do("rules_approve", confirmed=True)
    scenes = project.data["segments"]
    scenes[0].update(label="product", human_verified=False)
    project.do("candidates_save", segments=scenes)
    project.do("plan_save", clips=project.two_cuts(), subtitles=[{"text": "유료 광고", "start": 0, "end": 2}])
    first = validate(project.data, project.directory)
    assert [check["status"] for check in first["checks"]] == ["review", "met", "review"]
    with pytest.raises(ReelMateError, match="필수 브랜드 조건"):
        project.do("export")
    scenes = project.data["segments"]
    scenes[0]["human_verified"] = True
    project.do("candidates_save", segments=scenes)
    rule = project.data["rules"][2]
    project.do("confirm_rule", rule_id=rule["rule_id"], status="met", start=0, end=2, note="원본에서 로고 확인")
    result = validate(project.data, project.directory)
    assert result["valid"]
    assert result["checks"][0]["evidence_start"] == 0
    plan = project.data["plan"]
    project.do("plan_save", clips=plan["clips"], subtitles=[plan["subtitles"][0] | {"text": "광고 표시 수정"}])
    assert project.data["confirmations"] == {}
    assert validate(project.data, project.directory)["checks"][2]["status"] == "review"


@pytest.mark.parametrize("bad_clip, message", [
    ({"source_in": -1}, "원본 시작"),
    ({"source_out": 7}, "후보 구간"),
    ({"source_out": float("nan")}, "원본 종료"),
    ({"timeline_start": 5.1}, "빈 구간"),
    ({"segment_id": "0" * 32}, "사용할 수 없는 후보"),
    ({"asset_id": "0" * 32}, "원본과 후보"),
])
def test_reject_invalid_clip(project, media_samples, bad_clip, message):
    project.upload(media_samples[:2])
    first, second = project.two_cuts()
    with pytest.raises(ReelMateError, match=message):
        project.do("plan_save", clips=[first, second | bad_clip], subtitles=[])


def test_clip_lock_must_be_released_separately(project, media_samples):
    project.upload(media_samples)
    project.do("plan_save", clips=project.two_cuts(), subtitles=[])
    original = project.data["plan"]["clips"][0]
    project.do("clip_lock", clip_id=original["clip_id"], locked=True)
    one, two = project.data["plan"]["clips"]
    altered = one | {"locked": False, "source_in": 1, "source_out": 6}
    with pytest.raises(ReelMateError, match="잠근 컷"):
        project.do("plan_save", clips=[altered, two], subtitles=[])
    scenes = project.data["segments"]
    scenes[0]["excluded"] = True
    with pytest.raises(ReelMateError, match="잠근 컷의 후보"):
        project.do("candidates_save", segments=scenes)
    project.do("clip_replace", clip_id=two["clip_id"], method="local")
    final_one, final_two = project.data["plan"]["clips"]
    assert final_one == one
    assert final_two["asset_id"] != two["asset_id"]
    assert final_two["timeline_start"] == two["timeline_start"]
    project.do("clip_lock", clip_id=one["clip_id"], locked=False)
    project.do("plan_save", clips=[altered, final_two], subtitles=[])
    assert project.data["plan"]["clips"][0]["source_in"] == 1


def test_edit_keeps_existing_excluded_cuts_without_allowing_new_ones_or_output(project, media_samples):
    project.upload(media_samples[:2])
    project.do("plan_save", clips=project.two_cuts(), subtitles=[])
    project.do("candidates_save", segments=[scene | {"excluded": True} for scene in project.data["segments"]])
    clips = project.data["plan"]["clips"]

    project.do("plan_save", clips=clips, subtitles=[{"text": "수정한 자막", "start": 0, "end": 2}])
    assert project.data["plan"]["clips"] == clips
    assert project.data["plan"]["subtitles"][0]["text"] == "수정한 자막"
    with pytest.raises(ReelMateError, match="사용할 수 없는 후보"):
        project.do("plan_save", clips=[clips[0] | {"clip_id": None}, clips[1]], subtitles=[])
    for action in ("export", "capcut_export"):
        with pytest.raises(ReelMateError, match="사용할 수 없는 후보"):
            project.do(action)


def test_overlap_and_unsatisfied_duration(project, media_samples):
    project.upload(media_samples[:2])
    first, _ = project.two_cuts()
    with pytest.raises(ReelMateError, match="중복 사용"):
        project.do("plan_save", clips=[first, first | {"source_in": 1, "source_out": 2}], subtitles=[])
    project.do("plan_save", clips=[first], subtitles=[])
    assert not validate(project.data, project.directory)["valid"]
    with pytest.raises(ReelMateError, match="목표"):
        project.do("export")


def test_short_footage_can_fill_target_when_reuse_is_enabled(project, media_samples, tmp_path, monkeypatch):
    source = tmp_path / "촬영 원본 20초.mp4"
    run("ffmpeg", ["-v", "error", "-stream_loop", -1, "-i", media_samples[0], "-t", 20,
                   "-c:v", "libx264", "-c:a", "aac", source])
    project.upload([source])
    project.do("project_settings", **(project.settings | {"target_duration": 45, "aspect_ratio": "1:1"}))
    project.do("plan_create", method="local")
    assert project.data["plan"]["actual_duration"] == 20
    project.do("plan_create", method="local", allow_source_reuse=True)
    assert project.data["plan"]["actual_duration"] == 45

    def suggestion(request):
        assert request["fill_shortfall"] is True
        assert request["target_duration"] == 45
        return {
            "clips": [{"segment_id": request["candidates"][0]["segment_id"], "source_in": 0, "source_out": 5}],
            "subtitles": [{"text": "초안 자막", "start": 0, "end": 2}],
        }

    monkeypatch.setattr(project.service.gemini, "plan", suggestion)
    project.do("plan_create", method="gemini", allow_source_reuse=True)
    plan = project.data["plan"]
    assert plan["actual_duration"] == 45
    assert plan["clips"][0]["source_out"] == 5
    assert plan["subtitles"][0]["text"] == "초안 자막"
    assert plan["allow_source_reuse"]
    project.do("plan_save", clips=plan["clips"], subtitles=plan["subtitles"])
    assert validate(project.data, project.directory)["valid"]

    project.do("export")
    output = project.directory / project.data["outputs"][0]["directory"] / "preview.mp4"
    assert probe(output)["duration"] == 45


def test_long_footage_keeps_required_and_style_cuts_in_45_second_mp4(project, media_samples, tmp_path, monkeypatch):
    source = tmp_path / "촬영 원본 60초.mp4"
    inputs = [arg for color in ("black", "blue", "green", "red") for arg in
              ("-f", "lavfi", "-i", f"color={color}:s=160x120:d=15:r=30")]
    run("ffmpeg", ["-v", "error", *inputs, "-filter_complex", "concat=n=4:v=1:a=0",
                   "-c:v", "libx264", source])
    assert probe(source)["duration"] == 60
    project.upload([source])
    asset_id = project.data["assets"][0]["asset_id"]
    labels = ("unknown", "detail", "use", "product")
    project.do("candidates_save", segments=[
        {"asset_id": asset_id, "label": label, "start": index * 15, "end": (index + 1) * 15,
         "human_verified": label != "unknown"}
        for index, label in enumerate(labels)
    ])
    scenes = project.data["segments"]
    project.do("rules_save", rules=[{"type": "product_deadline", "value": "product", "deadline_sec": 2}])
    project.do("rules_approve", confirmed=True)
    profile_id = project.service.dispatch("profile_import", {
        "name": "제품에서 사용 장면으로", "avg_shot_length": 5, "approve": True,
        "preferred_sequence": ["product", "use", "detail"], "subtitle_style": {"position": "top"},
    })["profile_id"]
    project.do("project_settings", **(project.settings | {
        "target_duration": 45, "aspect_ratio": "1:1", "profile_id": profile_id,
    }))

    def suggestion(request):
        assert request["select_for_target"] is True
        assert request["style"]["preferred_sequence"] == ["product", "use", "detail"]
        return {
            "clips": [{"segment_id": s["segment_id"], "source_in": s["start"], "source_out": s["end"]}
                      for s in scenes],
            "subtitles": [
                {"text": "제외할 화면", "start": 0, "end": 2},
                {"text": "사용 방법", "start": 30, "end": 32},
                {"text": "제품 소개", "start": 45, "end": 47},
            ],
        }

    monkeypatch.setattr(project.service.gemini, "plan", suggestion)
    for method in ("local", "gemini"):
        project.do("plan_create", method=method, allow_source_reuse=True)
        plan = project.data["plan"]
        assert plan["actual_duration"] == 45
        assert not plan["allow_source_reuse"]
        assert [clip["source_in"] for clip in plan["clips"][:3]] == [45, 30, 15]
        assert all(clip["source_in"] >= 15 and clip["source_out"] - clip["source_in"] == 5
                   for clip in plan["clips"])
        assert validate(project.data, project.directory)["valid"]

    assert [(s["text"], s["start"], s["end"], s["style"]["position"])
            for s in plan["subtitles"]] == [("제품 소개", 0, 2, "top"), ("사용 방법", 5, 7, "top")]
    project.do("export")
    output = project.directory / project.data["outputs"][0]["directory"] / "preview.mp4"
    encoded_video = json.loads(run("ffprobe", [
        "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration,nb_frames", "-of", "json", output,
    ]).stdout)["streams"][0]
    assert (float(encoded_video["duration"]), int(encoded_video["nb_frames"])) == (45, 1350)


def test_unverified_rules_and_gemini_failure_leave_draft(project, media_samples):
    project.upload(media_samples[:2])
    project.do("guide_text", text="광고 문구를 넣으세요.")
    before = project.data
    with pytest.raises(ReelMateError, match="GEMINI_API_KEY"):
        project.do("guide_parse")
    assert project.data == before
    project.do("plan_save", clips=project.two_cuts(), subtitles=[])
    assert "규칙 목록을 승인하세요" in validate(project.data, project.directory)["errors"][0]


def test_gemini_uses_allowlisted_metadata_and_rejects_invalid_ids(project, media_samples, monkeypatch):
    project.upload(media_samples[:2])
    first, second = project.two_cuts()
    captured = []
    def suggestion(value):
        captured.append(value)
        return {"clips": [first, second | {"segment_id": "0" * 32}], "subtitles": []}
    monkeypatch.setattr(project.service.gemini, "plan", suggestion)
    before = project.data
    with pytest.raises(ReelMateError, match="사용할 수 없는 후보"):
        project.do("plan_create", method="gemini")
    assert project.data == before
    assert "path" not in json.dumps(captured)
    assert len(captured[0]["candidates"]) == 2


def read_frame(path, at):
    return run("ffmpeg", ["-v", "error", "-ss", at, "-i", path, "-frames:v", 1,
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout


def test_versioned_media_package_matches_timeline(project, media_samples):
    project.upload(media_samples[:2])
    project.do("plan_save", clips=project.two_cuts(), subtitles=[
        {"text": "릴메이트 한글 자막", "start": 1, "end": 2, "style": {"position": "top"}},
        {"text": "두 번째 자막", "start": 6, "end": 8, "style": {"position": "bottom"}},
    ])
    first = project.do("export")["output_version"]
    exported = project.data["outputs"][0]
    output = project.directory / exported["directory"]
    mp4 = output / "preview.mp4"
    metadata = probe(mp4)
    assert (metadata["width"], metadata["height"], metadata["duration"], metadata["fps"]) == (540, 960, 10, 30)
    assert metadata["has_audio"]
    a = read_frame(mp4, 0.5)
    b = read_frame(mp4, 1.5)
    c = read_frame(mp4, 5.1)
    assert a[0] > 200 and a[2] < 40 and c[2] > 200 and c[0] < 40
    top_band = slice(85 * 540 * 3, 180 * 540 * 3)
    assert a[top_band] != b[top_band]
    def pcm_peak(at):
        raw = run("ffmpeg", ["-v", "error", "-ss", at, "-i", mp4, "-t", "0.2",
                             "-vn", "-ac", "1", "-f", "s16le", "-"]).stdout
        return max(abs(int.from_bytes(raw[i:i + 2], "little", signed=True)) for i in range(0, len(raw), 2))
    assert pcm_peak(1) > 500
    assert pcm_peak(7) < 10
    assert "릴메이트 한글 자막" in (output / "subtitles.srt").read_text(encoding="utf-8-sig")
    with ZipFile(output / "editing-package.zip") as archive:
        assert archive.testzip() is None
        assert {"clips/001.mp4", "clips/002.mp4", "cuts.csv", "subtitles.srt", "edit_plan.json"} <= set(archive.namelist())
        edl = json.loads(archive.read("edit_plan.json"))
        assert edl["version"] == first
        assert edl["clips"][1]["timeline_start"] == 5
        assert edl["subtitles"][0]["style"] == {"position": "top"}
        assert '"path"' not in json.dumps(edl)
    assert project.do("export")["output_version"] == first
    assert project.data["outputs"][0] == exported
    plan = project.data["plan"]
    project.do("plan_save", clips=plan["clips"], subtitles=[plan["subtitles"][0] | {"text": "수정한 한글 자막"}])
    second = project.do("export")["output_version"]
    assert second > first
    reopened = Service(project.service.root).project(project.id)
    assert [item["version"] for item in reopened["outputs"]] == [first, second]
    assert "릴메이트 한글 자막" in (output / "subtitles.srt").read_text(encoding="utf-8-sig")


def test_confirmed_delete_removes_assets(project, media_samples):
    project.upload(media_samples[:1])
    with pytest.raises(ReelMateError, match="제품명"):
        project.do("project_delete", confirm="다른 이름")
    assert project.directory.exists()
    assert project.do("project_delete", confirm=project.settings["product"])["project_id"] is None
    assert not project.directory.exists()
