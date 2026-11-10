import base64
import binascii
import json
import logging
import os
import shutil
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

from . import analysis
from .ai import Gemini
from .capcut import CAPCUT_FILENAME, export_capcut
from .common import (
    ASPECTS, GUIDE_LIMIT, LABELS, PROJECT_VIDEO_LIMIT, VIDEO_LIMIT, ReelMateError,
    atomic_json, file_name, frames, items, now, number, object_id, record, seconds, string, uid,
)
from .exporter import OUTPUT_FILES, export
from .media import VIDEO_EXTENSIONS, executable, probe, thumbnail
from .planner import manual_draft, replace_selected
from .validation import clip_end, prepare_plan, rules_from_input, unique, validate


LOG = logging.getLogger("reelmate")
PROJECT_ACTIONS = {
    "project_settings", "upload", "guide_text", "guide_parse", "rules_save", "rules_approve",
    "clip_analyze", "candidates_save", "style_measure", "style_summarize", "plan_create", "plan_save",
    "clip_lock", "clip_replace", "confirm_rule", "transcribe", "transcript_apply", "export", "capcut_export",
}


def decode_upload(entry, limit):
    entry = record(entry, "업로드")
    encoded = entry.get("data")
    if not isinstance(encoded, str) or not 0 < len(encoded) <= ((limit + 2) // 3) * 4:
        raise ReelMateError(f"비어 있거나 {limit // 1024**2}MB를 초과한 파일입니다.")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ReelMateError("파일을 전송하지 못했습니다. 파일을 다시 선택하세요.") from exc
    if not 0 < len(data) <= limit:
        raise ReelMateError(f"파일 크기는 {limit // 1024**2}MB 이하여야 합니다.")
    return file_name(entry.get("name")), data


class Service:
    def __init__(self, root, gemini=None):
        self.root = Path(root).resolve()
        self.gemini = gemini or Gemini()
        self.lock = RLock()

    def directory(self, project_id):
        base = self.root / "projects"
        result = base / object_id(project_id, "프로젝트")
        if result.resolve() != result:
            raise ReelMateError("프로젝트 경로가 올바르지 않습니다.")
        return result

    def project(self, project_id):
        path = self.directory(project_id) / "project.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ReelMateError("저장된 프로젝트를 찾을 수 없습니다.") from exc
        except (OSError, ValueError) as exc:
            raise ReelMateError("프로젝트 데이터를 읽을 수 없습니다.") from exc

    def projects(self):
        values = []
        for path in (self.root / "projects").glob("*/project.json"):
            try:
                p = self.project(path.parent.name)
            except ReelMateError:
                continue
            values.append({key: p[key] for key in (
                "project_id", "brand", "product", "target_duration", "aspect_ratio", "updated_at",
            )} | {"source_count": sum(a["role"] == "source" for a in p["assets"]),
                  "output_count": len({item["version"] for item in p["outputs"] + p.get("capcut_exports", [])})})
        return sorted(values, key=lambda p: p["updated_at"], reverse=True)

    def profiles(self):
        result = []
        for path in (self.root / "profiles").glob("*.json"):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                LOG.warning("A saved style profile could not be read.")
        return sorted(result, key=lambda p: p["updated_at"], reverse=True)

    def profile(self, profile_id):
        if not profile_id:
            return None
        return next((p for p in self.profiles() if p["profile_id"] == profile_id), None)

    def settings(self, body):
        aspect = body.get("aspect_ratio")
        if not isinstance(aspect, str) or aspect not in ASPECTS:
            raise ReelMateError("출력 화면 비율을 선택하세요.")
        profile_id = body.get("profile_id") or None
        if profile_id:
            object_id(profile_id, "스타일")
            profile = self.profile(profile_id)
            if not profile or not profile["approved_at"]:
                raise ReelMateError("승인된 스타일을 선택하세요.")
        return {
            "brand": string(body.get("brand"), "브랜드명", 80),
            "product": string(body.get("product"), "제품명", 80),
            "target_duration": seconds(frames(number(body.get("target_duration"), "목표 길이", 1, 60))),
            "aspect_ratio": aspect, "profile_id": profile_id,
        }

    def dispatch(self, action, body, project_id=None, revision=None):
        body = record(body, "요청")
        with self.lock:
            if action == "project_create":
                return self._create_project(body)
            if action in ("profile_save", "profile_import"):
                return self._save_profile(body, project_id, revision, imported=action == "profile_import")
            if action not in PROJECT_ACTIONS | {"project_delete"}:
                raise ReelMateError("지원되지 않는 요청입니다.")
            project = self.project(project_id)
            if type(revision) is not int or project["revision"] != revision:
                raise ReelMateError("다른 창에서 프로젝트를 저장했습니다. 최신 내용을 확인한 뒤 다시 시도하세요.")
            folder = self.directory(project_id)
            if action == "project_delete":
                if body.get("confirm") != project["product"]:
                    raise ReelMateError("삭제를 확인하려면 프로젝트의 제품명을 입력하세요.")
                tombstone = folder.with_name(f".deleting-{project_id}")
                os.replace(folder, tombstone)
                try:
                    shutil.rmtree(tombstone)
                except OSError:
                    LOG.exception("A deleted ReelMate project could not be fully removed.")
                    return {"message": "프로젝트를 목록에서 제거했습니다. 잠긴 파일이 있어 디스크 정리는 완료되지 않았습니다.",
                            "project_id": None}
                return {"message": "프로젝트와 등록 자료, 생성 파일을 삭제했습니다.", "project_id": None}
            with ExitStack() as undo:
                message = getattr(self, f"_do_{action}")(project, folder, body, undo)
                project["revision"] += 1
                project["updated_at"] = now()
                project["history"].append({
                    "action": action, "message": message, "at": project["updated_at"],
                    "plan_version": project["plan"]["version"] if project["plan"] else None,
                })
                atomic_json(folder / "project.json", project)
                undo.pop_all()
            result = {"message": message, "project_id": project_id}
            if action == "export":
                result["output_version"] = project["plan"]["version"]
            if action == "capcut_export":
                result["capcut_version"] = project["plan"]["version"]
            return result

    def _create_project(self, body):
        project_id = uid()
        project = {
            "schema": 1, "project_id": project_id, "revision": 1,
            **self.settings(body), "created_at": now(), "updated_at": now(),
            "assets": [], "segments": [], "guide": None, "rules": [], "rules_approved": False,
            "rule_source": None, "confirmations": {}, "style_draft": None, "plan": None,
            "outputs": [], "history": [{"action": "project_create", "message": "프로젝트를 만들었습니다.",
                                         "at": now(), "plan_version": None}],
        }
        atomic_json(self.directory(project_id) / "project.json", project)
        return {"message": "프로젝트를 저장했습니다. 촬영 원본을 등록하세요.", "project_id": project_id}

    @staticmethod
    @contextmanager
    def stage(folder, category, undo):
        parent = folder / category
        parent.mkdir(exist_ok=True)
        batch_id = uid()
        destination = parent / batch_id
        with TemporaryDirectory(dir=folder) as tmp:
            work = Path(tmp) / "complete"
            work.mkdir()
            yield work, f"{category}/{batch_id}"
            if any(work.iterdir()):
                os.replace(work, destination)
                undo.callback(shutil.rmtree, destination, ignore_errors=True)

    @staticmethod
    def invalidate(project):
        project["confirmations"] = {}
        if project["plan"]:
            project["plan"]["version"] += 1

    def _do_project_settings(self, project, _folder, body, _undo):
        updated = self.settings(body)
        plan_fields = ("target_duration", "aspect_ratio", "profile_id")
        if project["plan"] and any(project[key] != updated[key] for key in plan_fields):
            project["plan"].update({key: updated[key] for key in plan_fields})
            self.invalidate(project)
        project.update(updated)
        return "프로젝트 설정을 저장했습니다."

    def _do_upload(self, project, folder, body, undo):
        role = body.get("role")
        if role not in ("source", "reference", "guide"):
            raise ReelMateError("자료 종류를 선택하세요.")
        files = items(body.get("files"), "업로드 파일", 1 if role == "guide" else 6)
        if not files:
            raise ReelMateError("등록할 파일을 선택하세요.")
        total = sum(a["size"] for a in project["assets"])
        with self.stage(folder, "media", undo) as (work, relative):
            for entry in files:
                name, data = decode_upload(entry, GUIDE_LIMIT if role == "guide" else VIDEO_LIMIT)
                extension = Path(name).suffix.lower()
                allowed = {".pdf", ".txt"} if role == "guide" else VIDEO_EXTENSIONS
                if extension not in allowed:
                    raise ReelMateError("지원되는 확장자의 파일을 선택하세요.")
                asset_id = uid()
                source = work / (asset_id + extension)
                source.write_bytes(data)
                path = f"{relative}/{source.name}"
                if role == "guide":
                    self._set_guide(project, name, path, analysis.read_brief(source))
                    continue
                total += len(data)
                if total > PROJECT_VIDEO_LIMIT:
                    raise ReelMateError("프로젝트의 영상 합계가 100MB를 초과합니다.")
                try:
                    metadata = probe(source)
                    thumb = work / f"{asset_id}.jpg"
                    thumbnail(source, thumb, 0, metadata["video_index"])
                except ReelMateError as exc:
                    raise ReelMateError(f"{name} · {exc}") from exc
                asset = {
                    "asset_id": asset_id, "project_id": project["project_id"], "filename": name,
                    "path": path, "role": role, "size": len(data), "thumbnail": f"{relative}/{thumb.name}",
                    **metadata,
                }
                project["assets"].append(asset)
                if role == "source":
                    project["segments"].append({
                        "segment_id": uid(), "asset_id": asset_id, "start": 0, "end": asset["duration"],
                        "label": "unknown", "similarity": None, "human_verified": False,
                        "excluded": False, "source": "asset", "model": None, "samples": [],
                        "thumbnail": asset["thumbnail"],
                    })
        return f"자료 {len(files)}개를 등록했습니다."

    def _set_guide(self, project, name, path, text):
        project["guide"] = {"filename": name, "path": path, "text": text}
        project.update(rules=[], rules_approved=False, rule_source=None)
        self.invalidate(project)

    def _do_guide_text(self, project, folder, body, undo):
        value = string(body.get("text"), "가이드 본문", 50_000)
        with self.stage(folder, "media", undo) as (work, relative):
            (work / "guide.txt").write_text(value, encoding="utf-8")
            self._set_guide(project, "직접 입력한 가이드.txt", f"{relative}/guide.txt", value)
        return "브랜드 가이드를 저장했습니다. 규칙을 작성하고 승인하세요."

    def _do_guide_parse(self, project, _folder, _body, _undo):
        if not project["guide"]:
            raise ReelMateError("브랜드 가이드를 먼저 등록하세요.")
        rules = self.gemini.parse_brief(project["guide"]["text"])
        project["rules"] = rules_from_input(rules, preserve_ids=False)
        project.update(rules_approved=False, rule_source=f"Gemini · {self.gemini.model}")
        self.invalidate(project)
        return f"Gemini가 규칙 {len(project['rules'])}개를 제안했습니다. 원문과 대조한 뒤 승인하세요."

    def _do_rules_save(self, project, _folder, body, _undo):
        project["rules"] = rules_from_input(body.get("rules"))
        project["rules_approved"] = False
        project["rule_source"] = "수동 입력" if not project["rule_source"] else project["rule_source"]
        self.invalidate(project)
        return "브랜드 규칙을 저장했습니다. 목록을 확인하고 승인하세요."

    def _do_rules_approve(self, project, _folder, body, _undo):
        if body.get("confirmed") is not True:
            raise ReelMateError("가이드 원문과 브랜드 규칙을 대조해 주세요.")
        project["rules_approved"] = True
        self.invalidate(project)
        return "브랜드 규칙을 승인했습니다."

    def _do_clip_analyze(self, project, folder, _body, undo):
        used = {c["asset_id"] for c in project["plan"]["clips"]} if project["plan"] else set()
        edited = {s["asset_id"] for s in project["segments"] if s["source"] == "manual"}
        assets = [a for a in project["assets"] if a["role"] == "source"
                  and a["asset_id"] not in (used | edited)]
        if not assets:
            raise ReelMateError("분석할 신규 원본이 없습니다. 보정했거나 편집안에 사용 중인 장면은 유지됩니다.")
        replace_ids = {a["asset_id"] for a in assets}
        with self.stage(folder, "analysis", undo) as (work, relative):
            segments = [s for s in project["segments"] if s["asset_id"] not in replace_ids]
            for asset in assets:
                segments.extend(analysis.clip_segments(asset, folder, work, relative))
            project["segments"] = segments
        return f"CLIP으로 원본 {len(assets)}개를 분석했습니다. 유사도와 원본 구간을 확인하세요."

    def _do_candidates_save(self, project, folder, body, undo):
        assets = {a["asset_id"]: a for a in project["assets"] if a["role"] == "source"}
        existing = {s["segment_id"]: s for s in project["segments"]}
        entries = items(body.get("segments"), "장면 후보", max(500, len(existing) + 20))
        result = []
        with self.stage(folder, "analysis", undo) as (work, relative):
            for entry in entries:
                entry = record(entry, "장면 후보")
                segment_id = object_id(entry["segment_id"], "후보") if entry.get("segment_id") else uid()
                asset_id = object_id(entry.get("asset_id"), "원본")
                asset = assets.get(asset_id)
                old = existing.get(segment_id)
                if not asset or (old and old["asset_id"] != asset_id):
                    raise ReelMateError("후보 구간의 원본을 확인하세요.")
                start = number(entry.get("start"), "구간 시작", 0, asset["duration"])
                end = number(entry.get("end"), "구간 종료", 0, asset["duration"])
                if frames(end - start) < 3:
                    raise ReelMateError("장면 후보는 0.1초 이상이어야 합니다.")
                label = entry.get("label")
                if not isinstance(label, str) or label not in LABELS:
                    raise ReelMateError("지원되는 장면 분류를 선택하세요.")
                updated = {
                    "segment_id": segment_id, "asset_id": asset_id, "start": start, "end": end,
                    "label": label, "excluded": entry.get("excluded") is True,
                    "human_verified": entry.get("human_verified") is True and label != "unknown",
                }
                if old and all(old[key] == value for key, value in updated.items()):
                    result.append(old)
                    continue
                thumb = old["thumbnail"] if old else asset["thumbnail"]
                same_evidence = old and (old["start"], old["end"], old["label"]) == (start, end, label)
                if not old or (old["start"], old["end"]) != (start, end):
                    filename = segment_id + ".jpg"
                    midpoint = round((start + end) / 2, 3)
                    thumbnail(folder / asset["path"], work / filename, midpoint, asset["video_index"])
                    thumb = f"{relative}/{filename}"
                result.append({
                    **updated, "source": "manual", "thumbnail": thumb,
                    "similarity": old["similarity"] if same_evidence else None,
                    "samples": old["samples"] if same_evidence else [],
                    "model": old["model"] if same_evidence else None,
                })
            unique(result, "segment_id", "후보")
            revised = {s["segment_id"]: s for s in result}
            if project["plan"]:
                for clip in project["plan"]["clips"]:
                    scene = revised.get(clip["segment_id"])
                    if clip["locked"] and (not scene or scene["excluded"] or
                                            not scene["start"] <= clip["source_in"] < clip["source_out"] <= scene["end"]):
                        raise ReelMateError("잠근 컷의 후보를 제외하거나 범위 밖으로 바꿀 수 없습니다.")
            if result != project["segments"]:
                self.invalidate(project)
            project["segments"] = result
        return "장면 후보를 저장했습니다."

    def _do_style_measure(self, project, folder, body, _undo):
        references = [a for a in project["assets"] if a["role"] == "reference"]
        project["style_draft"] = analysis.measure_style(
            references, folder, use_clip=body.get("clip") is True, use_ocr=body.get("ocr") is True,
        )
        return "레퍼런스 측정을 마쳤습니다. 관찰 내용을 보완한 뒤 스타일을 저장하세요."

    def _do_style_summarize(self, project, _folder, _body, _undo):
        draft = project["style_draft"]
        if not draft:
            raise ReelMateError("레퍼런스 스타일을 먼저 측정하세요.")
        evidence = [{key: value for key, value in entry.items() if key not in {"filename", "asset_id"}}
                    for entry in draft["evidence"]]
        result = self.gemini.summarize_style(evidence)
        draft["summary"] = string(result.get("summary"), "스타일 요약", 600)
        return "Gemini 스타일 요약을 초안에 추가했습니다."

    def _save_profile(self, body, project_id, revision, *, imported):
        source = None
        if not imported:
            profile_id = object_id(body.get("profile_id"), "스타일")
            source = self.profile(profile_id)
            if not source and project_id:
                project = self.project(project_id)
                source = project["style_draft"]
                if not source or source["profile_id"] != profile_id or project["revision"] != revision:
                    raise ReelMateError("측정 초안이 변경되었습니다. 현재 프로필을 다시 열어 주세요.")
            if source and source.get("updated_at") and body.get("updated_at") != source["updated_at"]:
                raise ReelMateError("저장된 스타일이 변경되었습니다. 최신 프로필을 다시 열어 주세요.")
        evidence = deepcopy(source["evidence"] if source else [])
        if imported:
            for item in items(body.get("evidence", []), "스타일 근거", 60):
                item = record(item, "스타일 근거")
                duration = number(item.get("duration"), "레퍼런스 길이", 0.1, 120)
                evidence.append({
                    "asset_id": object_id(item.get("asset_id"), "레퍼런스"),
                    "filename": file_name(item.get("filename")), "duration": duration,
                    "width": number(item.get("width"), "화면 너비", 1, 16384),
                    "height": number(item.get("height"), "화면 높이", 1, 16384),
                    "cuts": [number(cut, "컷 경계", 0, duration)
                             for cut in items(item.get("cuts", []), "컷 경계", 600)],
                    "avg_shot_length": number(item.get("avg_shot_length"), "평균 컷 길이", 0.1, 120),
                    "opening_label": item["opening_label"] if isinstance(item.get("opening_label"), str)
                    and item["opening_label"] in LABELS else "",
                    "first_product_sec": None if item.get("first_product_sec") is None else
                    number(item["first_product_sec"], "제품 등장", 0, duration),
                    "subtitle_observation": string(item.get("subtitle_observation", ""), "자막 관찰", 250, True),
                    "observation_source": string(item.get("observation_source", ""), "관찰 출처", 250, True),
                    "frame_labels": [self._import_frame(frame, duration)
                                     for frame in items(item.get("frame_labels", []), "표본", 36)],
                    "manual": self._observations(item.get("manual", {}), duration),
                })
        updates = {object_id(row.get("asset_id"), "레퍼런스"): row
                   for value in items(body.get("observations", []), "관찰", 60)
                   for row in [record(value, "관찰")]}
        for item in evidence:
            if item["asset_id"] in updates:
                item["manual"] = self._observations(updates[item["asset_id"]], item["duration"])
        saved = analysis.profile_from_input(body, evidence)
        saved.update(profile_id=source["profile_id"] if source else uid(),
                     approved_at=now() if body.get("approve") is True else None, updated_at=now())
        atomic_json(self.root / "profiles" / (saved["profile_id"] + ".json"), saved)
        return {"message": "편집 스타일을 승인해 저장했습니다." if saved["approved_at"] else "편집 스타일 초안을 저장했습니다.",
                "profile_id": saved["profile_id"]}

    @staticmethod
    def _import_frame(value, duration):
        frame = record(value, "CLIP 표본")
        label = frame.get("label")
        if not isinstance(label, str) or label not in LABELS:
            raise ReelMateError("스타일 표본의 장면 분류를 확인하세요.")
        return {"label": label, "time": number(frame.get("time"), "표본 시간", 0, duration),
                "similarity": number(frame.get("similarity"), "표본 유사도", -1, 1)}

    @staticmethod
    def _observations(row, duration):
        row = record(row, "관찰")
        first = row.get("first_product_sec")
        return {
            "opening": string(row.get("opening", ""), "첫 장면 관찰", 120, True),
            "first_product_sec": None if first is None else number(first, "제품 등장", 0, duration),
            "subtitle": string(row.get("subtitle", ""), "자막 관찰", 200, True),
        }

    def _accept_plan(self, project, value, origin, model=None):
        project["plan"] = prepare_plan(project, value, project["plan"], origin, model)
        project["confirmations"] = {}

    def _do_plan_create(self, project, _folder, body, _undo):
        if project["plan"] and any(c["locked"] for c in project["plan"]["clips"]):
            raise ReelMateError("잠근 컷이 있습니다. 검토 단계에서 잠금 해제 또는 선택 컷 재편집을 사용하세요.")
        profile = self.profile(project["profile_id"])
        if body.get("method") == "gemini":
            candidates = [{key: s[key] for key in
                           ("segment_id", "asset_id", "start", "end", "label", "human_verified", "similarity")}
                          for s in project["segments"] if not s["excluded"]]
            if not candidates or len(candidates) > 240:
                raise ReelMateError("Gemini 편집안을 만들려면 사용할 후보를 1~240개로 정리하세요.")
            style = {key: profile[key] for key in ("opening_style", "avg_shot_length", "preferred_sequence",
                                                  "subtitle_style", "pacing", "summary")} if profile else None
            value = self.gemini.plan({
                "brand": project["brand"], "product": project["product"], "target_duration": project["target_duration"],
                "aspect_ratio": project["aspect_ratio"], "candidates": candidates, "rules": project["rules"],
                "style": style,
            })
            if profile:
                for caption in value.get("subtitles", []) if isinstance(value.get("subtitles"), list) else []:
                    if isinstance(caption, dict):
                        caption["style"] = {"position": profile["subtitle_style"]["position"]}
            self._accept_plan(project, value, "gemini", self.gemini.model)
            return "Gemini 편집안 초안을 저장했습니다. 타임라인과 브랜드 조건을 검토하세요."
        self._accept_plan(project, manual_draft(project, profile), "local")
        return "등록한 장면으로 편집안 초안을 만들었습니다. 컷과 자막을 검토하세요."

    def _do_plan_save(self, project, _folder, body, _undo):
        previous = project["plan"]
        model = previous["model"] if previous else None
        self._accept_plan(project, body, "manual", model)
        return f"편집안 v{project['plan']['version']}을 저장했습니다."

    def _do_clip_lock(self, project, _folder, body, _undo):
        clip = self._clip(project, body)
        value = body.get("locked")
        if type(value) is not bool:
            raise ReelMateError("컷 잠금 상태를 확인하세요.")
        clip["locked"] = value
        project["plan"]["version"] += 1
        return "컷을 잠갔습니다." if value else "컷 잠금을 해제했습니다."

    def _clip(self, project, body):
        clip_id = object_id(body.get("clip_id"), "컷")
        clip = next((c for c in (project["plan"] or {}).get("clips", []) if c["clip_id"] == clip_id), None)
        if clip is None:
            raise ReelMateError("저장된 편집안에서 컷을 선택하세요.")
        return clip

    def _do_clip_replace(self, project, _folder, body, _undo):
        clip = self._clip(project, body)
        method = body.get("method")
        gemini = self.gemini if method == "gemini" else None
        prompt = string(body.get("prompt", ""), "재편집 요청", 400, True)
        value = replace_selected(project, clip["clip_id"], gemini, prompt)
        self._accept_plan(project, value, "gemini_revision" if gemini else "local_revision",
                          gemini.model if gemini else project["plan"]["model"])
        return "선택한 컷을 같은 길이의 다른 원본 구간으로 교체했습니다."

    def _do_confirm_rule(self, project, _folder, body, _undo):
        rule_id = object_id(body.get("rule_id"), "규칙")
        rule = next((rule for rule in project["rules"] if rule["rule_id"] == rule_id), None)
        if not project["plan"] or not project["rules_approved"] or not rule or rule["type"] != "manual":
            raise ReelMateError("편집안과 승인된 직접 확인 규칙이 필요합니다.")
        status = body.get("status")
        if status not in ("met", "unmet", "review"):
            raise ReelMateError("검수 결과를 선택하세요.")
        if status == "review":
            project["confirmations"].pop(rule_id, None)
        else:
            duration = project["plan"]["actual_duration"]
            start = number(body.get("start"), "근거 시작", 0, duration)
            end = number(body.get("end"), "근거 종료", 0, duration)
            if start >= end:
                raise ReelMateError("근거 종료는 시작보다 늦어야 합니다.")
            project["confirmations"][rule_id] = {
                "status": status, "start": start, "end": end,
                "note": string(body.get("note"), "검수 근거", 400), "at": now(),
            }
        project["plan"]["version"] += 1
        return "직접 검수 결과를 저장했습니다."

    def _do_transcribe(self, project, folder, body, _undo):
        asset_id = object_id(body.get("asset_id"), "원본")
        asset = next((a for a in project["assets"] if a["asset_id"] == asset_id and a["role"] == "source"), None)
        if not asset:
            raise ReelMateError("전사할 촬영 원본을 선택하세요.")
        asset["transcript"] = analysis.transcribe(asset, folder)
        return f"음성 전사 구간 {len(asset['transcript']['segments'])}개를 저장했습니다."

    def _do_transcript_apply(self, project, _folder, _body, _undo):
        plan = project["plan"]
        if not plan:
            raise ReelMateError("자막을 추가할 편집안이 필요합니다.")
        assets = {a["asset_id"]: a for a in project["assets"]}
        captions = list(plan["subtitles"])
        count = 0
        profile = self.profile(project["profile_id"])
        style = {"position": profile["subtitle_style"]["position"] if profile else "bottom"}
        for clip in plan["clips"]:
            chunks = assets[clip["asset_id"]].get("transcript", {}).get("segments", [])
            for chunk in chunks:
                start = max(chunk["start"], clip["source_in"])
                end = min(chunk["end"], clip["source_out"])
                if end <= start:
                    continue
                ts = seconds(frames(clip["timeline_start"] + start - clip["source_in"]))
                te = min(clip_end(clip), seconds(frames(clip["timeline_start"] + end - clip["source_in"])))
                if te <= ts or any(ts < c["end"] and te > c["start"] for c in captions):
                    continue
                if len(chunk["text"]) > 140 or len(captions) >= 120:
                    continue
                captions.append({"start": ts, "end": te, "text": chunk["text"], "style": style})
                count += 1
        if not count:
            raise ReelMateError("추가할 전사 구간이 없습니다. 원본 전사 또는 기존 자막의 겹침을 확인하세요.")
        self._accept_plan(project, {"clips": plan["clips"], "subtitles": captions}, "whisper", plan["model"])
        return f"전사에서 자막 초안 {count}개를 추가했습니다."

    def _do_export(self, project, folder, _body, undo):
        validation = validate(project, folder)
        if not validation["valid"]:
            raise ReelMateError(" ".join(validation["errors"]))
        version = project["plan"]["version"]
        old = next((o for o in project["outputs"] if o["version"] == version), None)
        if old and all((folder / old["directory"] / filename).is_file()
                       for filename, _, _ in OUTPUT_FILES.values()):
            return f"편집안 v{version}의 저장된 출력을 불러왔습니다."
        with self.stage(folder, "outputs", undo) as (work, relative):
            details = export(project, folder, work / "files", validation)
        project["outputs"] = [o for o in project["outputs"] if o["version"] != version]
        project["outputs"].append({"version": version, "directory": f"{relative}/files",
                                   "files": details, "created_at": now()})
        return f"편집안 v{version}의 MP4와 편집 패키지를 생성했습니다."

    def _do_capcut_export(self, project, folder, _body, undo):
        validation = validate(project, folder)
        if not validation["valid"]:
            raise ReelMateError(" ".join(validation["errors"]))
        version = project["plan"]["version"]
        exports = project.get("capcut_exports", [])
        saved = next((item for item in exports if item["version"] == version), None)
        if saved and (folder / saved["directory"] / CAPCUT_FILENAME).is_file():
            return f"편집안 v{version}의 CapCut 프로젝트 ZIP을 불러왔습니다."
        with self.stage(folder, "outputs", undo) as (work, relative):
            size = export_capcut(project, folder, work / "files")
        project["capcut_exports"] = [item for item in exports if item["version"] != version]
        project["capcut_exports"].append({
            "version": version, "directory": f"{relative}/files", "bytes": size, "created_at": now(),
        })
        return f"편집안 v{version}의 CapCut 프로젝트 ZIP을 생성했습니다."

    def capabilities(self):
        try:
            executable("ffmpeg")
            executable("ffprobe")
            media = True
        except ReelMateError:
            media = False
        try:
            model = analysis.clip_model_name()
        except ReelMateError:
            model = None
        return {
            "ffmpeg": media, "gemini": self.gemini.available,
            "gemini_model": self.gemini.model if self.gemini.available else None,
            "clip": bool(model and analysis.clip_available()), "clip_model": model,
            "whisper": analysis.whisper_available(), "ocr": bool(analysis.ocr_executable()),
        }
