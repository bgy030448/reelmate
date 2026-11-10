from pathlib import Path

from .common import (
    ASPECTS, LABELS, RULE_TYPES, ReelMateError, frames, items, number, object_id,
    record, seconds, string, uid,
)


LOCK_FIELDS = ("segment_id", "asset_id", "source_in", "source_out", "timeline_start")
POSITIONS = {"top", "middle", "bottom"}


def rules_from_input(value, preserve_ids=True):
    rules = []
    for entry in items(value, "브랜드 규칙", 100):
        entry = record(entry, "브랜드 규칙")
        kind = entry.get("type")
        if not isinstance(kind, str) or kind not in RULE_TYPES:
            raise ReelMateError("지원되는 브랜드 규칙 유형을 선택하세요.")
        value = entry.get("value")
        if kind in ("scene", "product_deadline"):
            if not isinstance(value, str) or value not in LABELS or value == "unknown":
                raise ReelMateError("필수 장면의 분류를 선택하세요.")
        elif kind in ("duration", "max_duration"):
            value = number(value, "브랜드 길이", 0.1, 60)
        else:
            value = string(value, "규칙 내용", 400)
        deadline = entry.get("deadline_sec")
        if deadline is not None:
            deadline = number(deadline, "확인 기한", 0, 60)
        if kind == "product_deadline" and deadline is None:
            raise ReelMateError("제품 노출 시점을 초 단위로 입력하세요.")
        rules.append({
            "rule_id": object_id(entry["rule_id"], "규칙") if preserve_ids and entry.get("rule_id") else uid(),
            "type": kind,
            "value": value,
            "description": string(entry.get("description", ""), "규칙 설명", 400, allow_empty=True),
            "required": entry.get("required", True) is not False,
            "deadline_sec": deadline if kind in {"scene", "product_deadline", "required_text"} else None,
        })
    unique(rules, "rule_id", "규칙")
    return rules


def unique(entries, id_field, name):
    if len({entry[id_field] for entry in entries}) != len(entries):
        raise ReelMateError(f"{name} ID가 중복되었습니다.")


def prepare_plan(project, value, previous=None, source="manual", model=None):
    value = record(value, "편집안")
    segment_map = {s["segment_id"]: s for s in project["segments"]}
    assets = {a["asset_id"]: a for a in project["assets"] if a["role"] == "source"}
    old_clips = {c["clip_id"]: c for c in previous["clips"]} if previous else {}
    clips = []
    cursor = 0
    for entry in items(value.get("clips"), "컷", 120):
        entry = record(entry, "컷")
        clip_id = object_id(entry["clip_id"], "컷") if entry.get("clip_id") else uid()
        segment = segment_map.get(object_id(entry.get("segment_id"), "후보"))
        if segment is None or segment["excluded"] or segment["asset_id"] not in assets:
            raise ReelMateError("사용할 수 없는 후보가 있습니다. 분석 단계에서 장면을 확인하세요.")
        asset_id = segment["asset_id"]
        if entry.get("asset_id", asset_id) != asset_id:
            raise ReelMateError("컷의 원본과 후보가 일치하지 않습니다.")
        start = number(entry.get("source_in"), "원본 시작")
        end = number(entry.get("source_out"), "원본 종료")
        count = frames(end - start)
        if count < 3 or not segment["start"] <= start < end <= min(segment["end"], assets[asset_id]["duration"]):
            raise ReelMateError("컷은 후보 구간 안에서 0.1초 이상이어야 합니다.")
        if "timeline_start" in entry and frames(number(entry["timeline_start"], "배치 시간", 0, 60)) != cursor:
            raise ReelMateError("컷 사이에 타임라인이 겹치거나 빈 구간이 있습니다.")
        if any(c["asset_id"] == asset_id and start < c["source_out"] and end > c["source_in"] for c in clips):
            raise ReelMateError("동일 원본의 시간 구간이 중복 사용되었습니다.")
        old = old_clips.get(clip_id)
        clips.append({
            "clip_id": clip_id, "segment_id": segment["segment_id"], "asset_id": asset_id,
            "source_in": start, "source_out": end, "timeline_start": seconds(cursor),
            "locked": bool(old and old["locked"]),
        })
        cursor += count
    if not clips or cursor > 60 * 30:
        raise ReelMateError("편집안에는 총 60초 이하의 컷이 한 개 이상 필요합니다.")
    unique(clips, "clip_id", "컷")
    current_clips = {clip["clip_id"]: clip for clip in clips}
    for old in old_clips.values():
        if old["locked"] and (
            old["clip_id"] not in current_clips
            or any(current_clips[old["clip_id"]][key] != old[key] for key in LOCK_FIELDS)
        ):
            raise ReelMateError("잠근 컷의 원본, 구간 또는 타임라인 위치를 바꿀 수 없습니다. 먼저 잠금을 해제하세요.")
    subtitles = []
    for entry in items(value.get("subtitles"), "자막", 120):
        entry = record(entry, "자막")
        start = number(entry.get("start"), "자막 시작", 0, 60)
        end = number(entry.get("end"), "자막 종료", 0, 60)
        style = record(entry.get("style", {}), "자막 스타일")
        position = style.get("position", "bottom")
        if not isinstance(position, str) or position not in POSITIONS:
            raise ReelMateError("자막 위치를 선택하세요.")
        if frames(start) >= frames(end) or frames(end) > cursor:
            raise ReelMateError("자막 시간은 편집 영상 안에서 시작보다 끝이 늦어야 합니다.")
        subtitle_id = object_id(entry["subtitle_id"], "자막") if entry.get("subtitle_id") else uid()
        old = next((s for s in (previous or {}).get("subtitles", []) if s["subtitle_id"] == subtitle_id), None)
        text = string(entry.get("text"), "자막 문구", 140)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        origin = old["source"] if old and old["text"] == text else source
        subtitles.append({
            "subtitle_id": subtitle_id, "text": text, "start": seconds(frames(start)),
            "end": seconds(frames(end)), "style": {"position": position},
            "source": origin, "editable": True,
        })
    unique(subtitles, "subtitle_id", "자막")
    subtitles.sort(key=lambda entry: entry["start"])
    if any(a["end"] > b["start"] for a, b in zip(subtitles, subtitles[1:])):
        raise ReelMateError("자막 시간이 겹칩니다.")
    return {
        "plan_id": previous["plan_id"] if previous else uid(),
        "version": (previous["version"] if previous else 0) + 1,
        "profile_id": project["profile_id"],
        "target_duration": project["target_duration"],
        "aspect_ratio": project["aspect_ratio"],
        "actual_duration": seconds(cursor),
        "clips": clips, "subtitles": subtitles, "source": source, "model": model,
    }


def clip_end(clip):
    return seconds(frames(clip["timeline_start"]) + frames(clip["source_out"] - clip["source_in"]))


def rule_result(rule, plan, segments, confirmation):
    deadline = rule["deadline_sec"]
    kind = rule["type"]
    value = rule["value"]
    status, start, end = "unmet", None, None
    if kind in ("duration", "max_duration"):
        actual = frames(plan["actual_duration"])
        passed = actual == frames(value) if kind == "duration" else actual <= frames(value)
        status = "met" if passed else "unmet"
        reason = f"편집안 길이 {plan['actual_duration']:.3f}초 · 기준 {value:g}초"
    elif kind in ("required_text", "forbidden_text"):
        phrase = " ".join(value.casefold().split())
        hits = [s for s in plan["subtitles"] if phrase in " ".join(s["text"].casefold().split())
                and (deadline is None or s["start"] <= deadline)]
        passed = bool(hits) if kind == "required_text" else not hits
        status = "met" if passed else "unmet"
        if hits:
            start, end = hits[0]["start"], hits[0]["end"]
            reason = f"자막에서 문구 확인 · {hits[0]['text']}"
        else:
            reason = "지정한 범위의 자막에 해당 문구가 없습니다."
    elif kind in ("scene", "product_deadline"):
        hits = [c for c in plan["clips"] if c["segment_id"] in segments
                and segments[c["segment_id"]]["label"] == value
                and (deadline is None or c["timeline_start"] <= deadline)]
        confirmed = next((c for c in hits if segments[c["segment_id"]]["human_verified"]), None)
        if confirmed:
            status, start, end = "met", confirmed["timeline_start"], clip_end(confirmed)
            reason = f"사람이 확인한 {LABELS[value]} 장면을 사용했습니다."
        elif hits:
            status, start, end = "review", hits[0]["timeline_start"], clip_end(hits[0])
            reason = "후보 장면이 있습니다. 분석 단계에서 원본 구간의 라벨을 확인하세요."
        else:
            reason = "기한 내 사용된 일치 장면이 없습니다. 장면 보정 또는 추가 촬영이 필요합니다."
    elif confirmation:
        status, start, end = confirmation["status"], confirmation["start"], confirmation["end"]
        reason = confirmation["note"]
    else:
        status = "review"
        reason = "원본과 타임라인을 확인하고 근거 시간과 검수 결과를 남겨 주세요."
    return {
        "rule_id": rule["rule_id"], "required": rule["required"], "status": status,
        "reason": reason, "evidence_start": start, "evidence_end": end,
    }


def validate(project, directory):
    plan = project["plan"]
    if not plan:
        return {"valid": False, "errors": ["검토 단계에서 편집안을 생성하세요."], "checks": []}
    errors = []
    if plan["aspect_ratio"] not in ASPECTS:
        errors.append("출력 비율을 확인하세요.")
    try:
        normalized = prepare_plan(project, plan, previous=plan)
        if frames(normalized["actual_duration"]) != frames(plan["actual_duration"]):
            errors.append("편집안의 총 길이와 컷의 합이 일치하지 않습니다.")
    except ReelMateError as exc:
        errors.append(str(exc))
    if frames(plan["actual_duration"]) != frames(project["target_duration"]):
        errors.append(f"목표 {project['target_duration']:g}초에 맞춰 주세요. 현재 {plan['actual_duration']:g}초입니다.")
    assets = {a["asset_id"]: a for a in project["assets"]}
    missing = {c["asset_id"] for c in plan["clips"] if c["asset_id"] not in assets
               or not (Path(directory) / assets[c["asset_id"]]["path"]).is_file()}
    if missing:
        errors.append("편집안에서 참조한 원본 파일이 없습니다.")
    if (project["guide"] or project["rules"]) and not project["rules_approved"]:
        errors.append("브랜드 가이드의 조건을 구조화하고 규칙 목록을 승인하세요.")
    segments = {s["segment_id"]: s for s in project["segments"]}
    checks = [rule_result(rule, plan, segments, project["confirmations"].get(rule["rule_id"]))
              for rule in project["rules"]]
    if any(c["required"] and c["status"] != "met" for c in checks):
        errors.append("필수 브랜드 조건이 모두 충족되어야 내보낼 수 있습니다.")
    return {"valid": not errors, "errors": errors, "checks": checks}
