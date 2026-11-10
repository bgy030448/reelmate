from .common import FPS, ReelMateError, frames, seconds


def available_intervals(segment, clips):
    cursor, stop = segment["start"], segment["end"]
    occupied = sorted((c["source_in"], c["source_out"]) for c in clips
                      if c["asset_id"] == segment["asset_id"])
    for start, end in occupied:
        if start >= stop:
            break
        if cursor < start:
            yield cursor, start
        cursor = max(cursor, end)
    if cursor < stop:
        yield cursor, stop


def proposed_clip(segment, start, end, count):
    stop = min(round(start + count / FPS, 3), end)
    return {"segment_id": segment["segment_id"], "asset_id": segment["asset_id"],
            "source_in": start, "source_out": stop}


def manual_draft(project, profile):
    target = frames(project["target_duration"])
    desired = frames(profile["avg_shot_length"]) if profile else 90
    sequence = profile["preferred_sequence"] if profile else []
    required = sorted(
        (rule for rule in project["rules"] if rule["required"] and rule["type"] in ("scene", "product_deadline")),
        key=lambda rule: rule["deadline_sec"] if rule["deadline_sec"] is not None else 60,
    )
    segments = [s for s in project["segments"] if not s["excluded"]]
    labels = {s["segment_id"]: s["label"] for s in segments}
    clips = []
    remaining = target
    while remaining >= 3 and len(clips) < 120:
        used_labels = {labels[c["segment_id"]] for c in clips}
        needs = [r["value"] for r in required if r["value"] not in used_labels]
        preferred = sequence[len(clips) % len(sequence)] if sequence else None
        last_id = clips[-1]["asset_id"] if clips else None

        def priority(s):
            rule_rank = needs.index(s["label"]) if s["label"] in needs and s["human_verified"] else len(needs)
            return (rule_rank, s["label"] != preferred, s["asset_id"] == last_id)

        chosen = None
        for segment in sorted(segments, key=priority):
            for start, end in available_intervals(segment, clips):
                count = min(frames(end - start), max(3, desired), remaining)
                if remaining - count in (1, 2) and frames(end - start) >= remaining:
                    count = remaining
                if count >= 3:
                    chosen = proposed_clip(segment, start, end, count)
                    break
            if chosen:
                break
        if chosen is None:
            break
        clips.append(chosen)
        remaining -= frames(chosen["source_out"] - chosen["source_in"])
    if not clips:
        raise ReelMateError("사용할 수 있는 장면이 없습니다. 신규 원본과 제외 상태를 확인하세요.")
    return {"clips": clips, "subtitles": []}


def replace_selected(project, clip_id, gemini=None, prompt=""):
    plan = project["plan"]
    selected = next((clip for clip in plan["clips"] if clip["clip_id"] == clip_id), None)
    if selected is None or selected["locked"]:
        raise ReelMateError("잠금이 해제된 컷을 선택하세요.")
    count = frames(selected["source_out"] - selected["source_in"])
    options = []
    for segment in project["segments"]:
        if segment["excluded"]:
            continue
        # Require a different piece of footage and keep every other clip unchanged.
        for start, end in available_intervals(segment, plan["clips"]):
            if frames(end - start) >= count:
                options.append({
                    "segment_id": segment["segment_id"], "label": segment["label"],
                    "start": start, "end": end,
                })
    if not options:
        raise ReelMateError("같은 길이로 교체할 미사용 구간이 없습니다. 후보를 추가하거나 컷 길이를 줄이세요.")
    if gemini:
        replacement = gemini.replace_clip({"duration": seconds(count), "intervals": options[:240], "request": prompt})
        fits = False
        for option in options[:240]:
            start, end = replacement.get("source_in"), replacement.get("source_out")
            if (replacement.get("segment_id") == option["segment_id"]
                and type(start) in (float, int) and type(end) in (float, int)
                and option["start"] <= start < end <= option["end"]
                and frames(end - start) == count):
                fits = True
                break
        if not fits:
            raise ReelMateError("Gemini가 지정한 길이와 허용 구간을 지키지 못했습니다. 다시 시도하세요.")
    else:
        option = options[0]
        replacement = {"segment_id": option["segment_id"], "source_in": option["start"],
                       "source_out": min(option["end"], round(option["start"] + count / FPS, 3))}
    replacement.update({"clip_id": selected["clip_id"], "timeline_start": selected["timeline_start"]})
    return {
        "clips": [replacement if clip["clip_id"] == clip_id else clip for clip in plan["clips"]],
        "subtitles": plan["subtitles"],
    }
