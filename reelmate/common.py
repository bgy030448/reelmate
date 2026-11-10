import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
FPS = 30
ASPECTS = {"9:16": (540, 960), "16:9": (960, 540), "1:1": (720, 720)}
VIDEO_LIMIT = 20 * 1024**2
PROJECT_VIDEO_LIMIT = 100 * 1024**2
GUIDE_LIMIT = 5 * 1024**2
LABELS = {
    "unknown": "미분류",
    "opening": "오프닝 / 훅",
    "product": "제품 첫 소개",
    "detail": "제품 디테일",
    "use": "제품 사용",
    "package": "패키지",
    "lifestyle": "라이프스타일",
    "person": "인물",
    "space": "공간",
    "closing": "마무리 / CTA",
}
RULE_TYPES = {
    "scene": "필수 장면",
    "product_deadline": "제품 노출 시점",
    "required_text": "필수 자막 문구",
    "forbidden_text": "금지 자막 문구",
    "duration": "정확한 길이 (초)",
    "max_duration": "최대 길이 (초)",
    "manual": "화면·음성 직접 확인",
}


class ReelMateError(ValueError):
    """A message suitable for display in the editing UI."""


def uid():
    return uuid4().hex


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def record(value, name):
    if not isinstance(value, dict):
        raise ReelMateError(f"{name} 항목의 형식이 잘못되었습니다.")
    return value


def items(value, name, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ReelMateError(f"{name} 목록은 최대 {limit}개까지 입력할 수 있습니다.")
    return value


def string(value, name, max_len=120, allow_empty=False):
    if not isinstance(value, str):
        raise ReelMateError(f"{name}에 텍스트를 입력하세요.")
    value = value.strip()
    if (not value and not allow_empty) or len(value) > max_len or "\x00" in value:
        raise ReelMateError(f"{name}은(는) {max_len}자 이내로 입력하세요.")
    return value


def number(value, name, low=0, high=120):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low <= value <= high
        or not math.isfinite(value)
    ):
        raise ReelMateError(f"{name}은(는) {low}~{high} 사이의 숫자로 입력하세요.")
    return round(float(value), 3)


def object_id(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ReelMateError(f"{name} ID가 올바르지 않습니다.")
    return value


def frames(seconds):
    return round(seconds * FPS)


def seconds(frame_count):
    return round(frame_count / FPS, 3)


def file_name(value):
    name = string(value, "파일명", 180)
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name in {".", ".."}:
        raise ReelMateError("파일명에서 경로 구분자나 특수 문자를 제거하세요.")
    return name


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".tmp") as handle:
            tmp = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def atomic_json(path, data):
    atomic_write(path, json_text(data).encode("utf-8"))
