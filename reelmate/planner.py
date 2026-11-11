from collections import Counter
from math import ceil

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


def available_footage_frames(project):
    ranges = sorted((s["asset_id"], s["start"], s["end"]) for s in project["segments"] if not s["excluded"])
    merged = []
    for asset_id, start, end in ranges:
        if merged and merged[-1][0] == asset_id and start <= merged[-1][2]:
            merged[-1][2] = max(merged[-1][2], end)
        else:
            merged.append([asset_id, start, end])
    return sum(frames(end - start) for _, start, end in merged)


def manual_draft(project, profile, initial_clips=(), *, allow_source_reuse=False):
    target = frames(project["target_duration"])
    desired = frames(profile["avg_shot_length"]) if profile else 90
    sequence = profile["preferred_sequence"] if profile else []
    required = sorted(
        (rule for rule in project["rules"] if rule["required"] and rule["type"] in ("scene", "product_deadline")),
        key=lambda rule: rule["deadline_sec"] if rule["deadline_sec"] is not None else 60,
    )
    segments = [s for s in project["segments"] if not s["excluded"]]
    labels = {s["segment_id"]: s["label"] for s in segments}
    clips = list(initial_clips)
    remaining = target - sum(frames(c["source_out"] - c["source_in"]) for c in clips)
    if allow_source_reuse and remaining in (1, 2):
        last = clips.pop()
        count = frames(last["source_out"] - last["source_in"])
        remaining += count
        shortened = remaining - 3
        if shortened >= 3:
            clips.append(proposed_clip(last, last["source_in"], last["source_out"], shortened))
            remaining -= shortened
    pass_start = 0
    while remaining >= 3 and len(clips) < 120:
        used_labels = {labels[c["segment_id"]] for c in clips}
        needs = [r["value"] for r in required if r["value"] not in used_labels]
        preferred = sequence[len(clips) % len(sequence)] if sequence else None
        last_id = clips[-1]["asset_id"] if clips else None

        def priority(s):
            rule_rank = needs.index(s["label"]) if s["label"] in needs and s["human_verified"] else len(needs)
            return (rule_rank, s["label"] != preferred, s["asset_id"] == last_id)

        chosen = None
        preferred_length = max(3, desired)
        if allow_source_reuse:
            preferred_length = max(preferred_length, ceil(remaining / (120 - len(clips))))
        for segment in sorted(segments, key=priority):
            for start, end in available_intervals(segment, clips[pass_start:]):
                available = frames(end - start)
                count = min(available, preferred_length, remaining)
                if remaining - count in (1, 2):
                    if available >= remaining:
                        count = remaining
                    elif allow_source_reuse:
                        count = remaining - 3
                if count >= 3:
                    chosen = proposed_clip(segment, start, end, count)
                    break
            if chosen:
                break
        if chosen is None:
            if allow_source_reuse and pass_start < len(clips):
                pass_start = len(clips)
                continue
            break
        clips.append(chosen)
        remaining -= frames(chosen["source_out"] - chosen["source_in"])
    if not clips:
        raise ReelMateError("사용할 수 있는 장면이 없습니다. 신규 원본과 제외 상태를 확인하세요.")
    if allow_source_reuse and remaining != 0:
        raise ReelMateError("현재 장면 후보와 컷 수 제한으로 목표 길이를 채울 수 없습니다. 더 긴 후보를 추가하세요.")
    return {"clips": clips, "subtitles": []}


def fit_long_footage(project, profile, proposal=None):
    target = frames(project["target_duration"])
    desired = max(3, frames(profile["avg_shot_length"])) if profile else 90
    sequence = profile["preferred_sequence"] if profile else []
    segments = {s["segment_id"]: s for s in project["segments"] if not s["excluded"]}
    suggested = proposal["clips"] if proposal else []
    candidates = [
        {**segments[c["segment_id"]], "start": c["source_in"], "end": c["source_out"], "suggested": True}
        for c in suggested
    ] + list(segments.values())

    # A label can satisfy several scene rules. Reserve it for the earliest deadline.
    deadlines = {}
    for rule in project["rules"]:
        if rule["required"] and rule["type"] in ("scene", "product_deadline"):
            label = rule["value"]
            deadline = target if rule["deadline_sec"] is None else frames(rule["deadline_sec"])
            deadlines[label] = min(deadline, deadlines.get(label, target))
    labels = {s["label"] for s in segments.values()}
    required = sorted((deadline, label) for label, deadline in deadlines.items() if label in labels)

    clips = []
    remaining = target

    def append_cut(options, maximum, minimum=3):
        nonlocal remaining
        for segment in options:
            for start, end in available_intervals(segment, clips):
                available = frames(end - start)
                count = min(available, maximum, remaining)
                if remaining - count in (1, 2):
                    count = remaining if min(available, maximum) >= remaining else remaining - 3
                if count >= minimum:
                    clip = proposed_clip(segment, start, end, count)
                    clips.append(clip)
                    remaining -= frames(clip["source_out"] - clip["source_in"])
                    return True
        return False

    for index, (_, label) in enumerate(required):
        later = required[index + 1:]
        # Leave room to start subsequent required scenes on time.
        limit = min([remaining - 3 * len(later)] + [
            deadline - (target - remaining) - 3 * offset
            for offset, (deadline, _) in enumerate(later)
        ])
        options = sorted((s for s in candidates if s["label"] == label),
                         key=lambda s: not s["human_verified"])
        append_cut(options, max(3, min(desired, limit)))

    while remaining and len(clips) < 120:
        preferred = sequence[len(clips) % len(sequence)] if sequence else None
        counts = Counter(c["segment_id"] for c in clips)
        last_id = clips[-1]["segment_id"] if clips else None
        options = sorted(candidates, key=lambda s: (
            s["label"] != preferred,
            s["label"] == "unknown",
            s["segment_id"] == last_id,
            not s.get("suggested", False),
            counts[s["segment_id"]],
        ))
        minimum = max(3, ceil(remaining / (120 - len(clips))))
        maximum = max(desired, minimum)
        if not append_cut(options, maximum, minimum):
            if not append_cut(options, remaining):
                break

    if remaining:
        raise ReelMateError("겹치지 않는 컷으로 목표 길이를 맞추지 못했습니다. 분석에서 후보 구간을 확인하세요.")
    subtitles = remap_subtitles(proposal, clips) if proposal else []
    return {"clips": clips, "subtitles": subtitles}


def remap_subtitles(proposal, clips):
    # Map each retained piece of the proposed timeline to its new placement.
    mappings = []
    cursor = 0
    for clip in clips:
        length = frames(clip["source_out"] - clip["source_in"])
        for original in proposal["clips"]:
            if original["asset_id"] != clip["asset_id"]:
                continue
            shift = frames(clip["source_in"] - original["source_in"])
            start = max(0, shift)
            end = min(frames(original["source_out"] - original["source_in"]), shift + length)
            if start < end:
                old_at = frames(original["timeline_start"])
                mappings.append((old_at + start, old_at + end, cursor - shift - old_at))
        cursor += length

    adjusted = []
    for subtitle in proposal["subtitles"]:
        start, end = frames(subtitle["start"]), frames(subtitle["end"])
        pieces = sorted((max(start, left) + shift, min(end, right) + shift)
                        for left, right, shift in mappings if max(start, left) < min(end, right))
        merged = []
        for left, right in pieces:
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        if merged:
            left, right = max(merged, key=lambda piece: piece[1] - piece[0])
            adjusted.append((left, right, subtitle))

    subtitles = []
    previous_end = 0
    for left, right, subtitle in sorted(adjusted, key=lambda entry: entry[:2]):
        left = max(left, previous_end)
        if left < right:
            subtitles.append({**subtitle, "start": seconds(left), "end": seconds(right)})
            previous_end = right
    return subtitles


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
