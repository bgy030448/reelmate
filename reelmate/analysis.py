import importlib.util
import os
import re
import shutil
import subprocess
from collections import Counter
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from pypdf import PdfReader

from .common import LABELS, ROOT, ReelMateError, number, record, string, uid
from .media import INPUT_OPTIONS, run, sample_frames, shot_boundaries


CLIP_PROMPTS = {
    "opening": "an attention grabbing opening shot in a short social media video",
    "product": "a person holding up a retail product to introduce it to the camera",
    "detail": "a close-up of the texture or small details of a retail product",
    "use": "a person applying or using a consumer product",
    "package": "a product box or retail packaging in an unboxing shot",
    "lifestyle": "a lifestyle scene with a product in an everyday setting",
    "person": "a talking face or a portrait of a person",
    "space": "a room or location with no people or products",
    "closing": "a presenter waving goodbye at the end of a short video",
}
PRODUCT_LABELS = {"product", "detail", "use", "package"}
OCR_LANGUAGES = "kor+eng"


def clip_model_name():
    value = os.getenv("REELMATE_CLIP_MODEL", "openai/clip-vit-base-patch32")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value) or any(part in (".", "..") for part in value.split("/")):
        raise ReelMateError("REELMATE_CLIP_MODEL에 제공자/모델 형식의 Hugging Face ID를 입력하세요.")
    return value


def whisper_model_name():
    value = os.getenv("REELMATE_WHISPER_MODEL", "base")
    if not re.fullmatch(r"(?:[\w.-]+/)?[\w.-]+", value) or any(part in (".", "..") for part in value.split("/")):
        raise ReelMateError("REELMATE_WHISPER_MODEL에 모델 이름 또는 제공자/모델 ID를 입력하세요.")
    return value


def clip_available():
    return all(importlib.util.find_spec(dep) is not None for dep in ("torch", "transformers"))


def whisper_available():
    return importlib.util.find_spec("faster_whisper") is not None


def ocr_executable():
    return os.getenv("REELMATE_TESSERACT") or shutil.which("tesseract")


def read_brief(path):
    if path.suffix == ".txt":
        data = path.read_bytes()
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp949")
            except UnicodeDecodeError as exc:
                raise ReelMateError("가이드 텍스트는 UTF-8 또는 CP949로 저장하세요.") from exc
    else:
        try:
            pdf = PdfReader(path)
            if pdf.is_encrypted or len(pdf.pages) > 80:
                raise ReelMateError("잠금이 없는 80페이지 이하 PDF를 사용하세요.")
            pieces = []
            total = 0
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                total += len(page_text)
                if total > 50_000:
                    raise ReelMateError("가이드 본문은 최대 50,000자까지 지원합니다.")
                pieces.append(page_text)
            text = "\n".join(pieces)
        except ReelMateError:
            raise
        except Exception as exc:
            raise ReelMateError("PDF 본문을 읽지 못했습니다. PDF를 다시 저장하거나 텍스트를 입력하세요.") from exc
    if not text.strip():
        raise ReelMateError("가이드에 읽을 수 있는 본문이 없습니다. 스캔 PDF는 텍스트로 옮겨 입력하세요.")
    return string(text, "가이드 본문", 50_000)


@lru_cache(maxsize=1)
def load_clip(model_name):
    if not clip_available():
        raise ReelMateError("CLIP 의존성을 설치한 뒤 서버를 다시 시작하세요.")
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        cache = ROOT / ".tools" / "models" / "clip"
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        try:
            model = CLIPModel.from_pretrained(model_name, cache_dir=cache, local_files_only=True)
            processor = CLIPProcessor.from_pretrained(model_name, cache_dir=cache, use_fast=False, local_files_only=True)
        except OSError:
            model = CLIPModel.from_pretrained(model_name, cache_dir=cache, token=False)
            processor = CLIPProcessor.from_pretrained(model_name, cache_dir=cache, token=False, use_fast=False)
    except Exception as exc:
        raise ReelMateError("CLIP 가중치를 불러오지 못했습니다. 모델 이름, 설치와 최초 다운로드 연결을 확인하세요.") from exc
    return torch, model.eval(), processor


def classify_frames(paths, model_name):
    torch, model, processor = load_clip(model_name)
    labels = list(CLIP_PROMPTS)
    scores = []
    try:
        for offset in range(0, len(paths), 8):
            images = []
            for path in paths[offset:offset + 8]:
                with Image.open(path) as image:
                    images.append(image.convert("RGB"))
            inputs = processor(text=list(CLIP_PROMPTS.values()), images=images,
                               padding=True, return_tensors="pt")
            with torch.inference_mode():
                cosine = model(**inputs).logits_per_image / model.logit_scale.exp()
                values, indices = cosine.max(dim=1)
            scores.extend((labels[index], round(value, 4))
                          for value, index in zip(values.tolist(), indices.tolist(), strict=True))
    except Exception as exc:
        raise ReelMateError("CLIP 추론에 실패했습니다. 원본 영상과 설치된 모델을 확인하세요.") from exc
    return scores


def clip_segments(asset, directory, output, relative):
    model_name = clip_model_name()
    with TemporaryDirectory(dir=output) as temp:
        paths = sample_frames(directory / asset["path"], asset, Path(temp))
        scores = classify_frames(paths, model_name)
        step = asset["duration"] / len(scores)
        segments = []
        for index, (label, score) in enumerate(scores):
            end = round((index + 1) * step, 3)
            sample = {"time": round((index + 0.5) * step, 3), "label": label, "similarity": score}
            if segments and segments[-1]["label"] == label:
                segment = segments[-1]
                segment["end"] = end
                segment["samples"].append(sample)
                if score > segment["similarity"]:
                    segment["similarity"] = score
                    shutil.copyfile(paths[index], output / (segment["segment_id"] + ".jpg"))
                continue
            segment_id = uid()
            filename = segment_id + ".jpg"
            shutil.copyfile(paths[index], output / filename)
            segments.append({
                "segment_id": segment_id, "asset_id": asset["asset_id"],
                "start": round(index * step, 3), "end": end,
                "label": label, "similarity": score, "human_verified": False, "excluded": False,
                "source": "clip", "model": model_name, "samples": [sample],
                "thumbnail": f"{relative}/{filename}",
            })
    return segments


def ocr_region(path):
    binary = ocr_executable()
    try:
        result = subprocess.run(
            [binary, str(path), "stdout", "-l", OCR_LANGUAGES, "--psm", "11", "tsv"],
            capture_output=True, timeout=20, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with Image.open(path) as image:
            height = image.height
        words = [line.split("\t", 11) for line in result.stdout.decode("utf-8").splitlines()[1:]]
        centers = [(int(row[7]) + int(row[9]) / 2) / height for row in words
                   if len(row) == 12 and row[11].strip() and float(row[10]) >= 45]
        if not centers:
            return None
        center = sorted(centers)[len(centers) // 2]
        return "top" if center < 1 / 3 else "bottom" if center >= 2 / 3 else "middle"
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ReelMateError("OCR을 실행하지 못했습니다. Tesseract와 kor/eng 언어 데이터를 확인하세요.") from exc


def measure_style(assets, directory, *, use_clip=False, use_ocr=False):
    if len(assets) < 3:
        raise ReelMateError("스타일을 측정하려면 완성 레퍼런스를 3편 이상 등록하세요.")
    evidence = []
    cut_lengths = []
    text_regions = Counter()
    for asset in assets:
        path = directory / asset["path"]
        boundaries = shot_boundaries(path, asset)
        lengths = [end - start for start, end in zip(boundaries, boundaries[1:])]
        cut_lengths.extend(lengths)
        info = {
            "asset_id": asset["asset_id"], "filename": asset["filename"],
            "duration": asset["duration"], "width": asset["width"], "height": asset["height"],
            "cuts": boundaries[1:-1], "avg_shot_length": round(sum(lengths) / len(lengths), 2),
            "opening_label": "", "first_product_sec": None, "subtitle_observation": "",
            "observation_source": "", "frame_labels": [],
        }
        if asset["subtitle_index"] is not None:
            track = run("ffmpeg", ["-v", "error", "-nostdin", *INPUT_OPTIONS, "-i", path,
                                   "-map", f"0:{asset['subtitle_index']}", "-f", "srt", "-"]).stdout
            count = track.count(b" --> ")
            info["subtitle_observation"] = f"텍스트 자막 트랙 {count}개 구간"
        if use_clip or use_ocr:
            with TemporaryDirectory(dir=directory) as temp:
                samples = sample_frames(path, asset, Path(temp), max_frames=16)
                if use_clip:
                    scores = classify_frames(samples, clip_model_name())
                    times = [round((i + 0.5) * asset["duration"] / len(scores), 3)
                             for i in range(len(scores))]
                    info["opening_label"] = scores[0][0]
                    info["first_product_sec"] = next((time for time, (label, _) in zip(times, scores)
                                                      if label in PRODUCT_LABELS), None)
                    info["frame_labels"] = [
                        {"time": time, "label": label, "similarity": score}
                        for time, (label, score) in zip(times, scores, strict=True)
                    ]
                    info["observation_source"] = f"CLIP · {clip_model_name()} · 표본 추정"
                if use_ocr:
                    regions = [ocr_region(frame) for frame in samples]
                    counts = {r: regions.count(r) for r in ("top", "middle", "bottom")}
                    text_regions.update(counts)
                    note = f"OCR 화면 글자 {sum(counts.values())}/{len(samples)}프레임"
                    if sum(counts.values()):
                        top = max(counts, key=counts.get)
                        note += f" · 최빈 영역 { {'top': '상단', 'middle': '중앙', 'bottom': '하단'}[top] }"
                    info["subtitle_observation"] = " · ".join(filter(None, [info["subtitle_observation"], note]))
        evidence.append(info)
    average = round(sum(cut_lengths) / len(cut_lengths), 2)
    openings = Counter(item["opening_label"] for item in evidence if item["opening_label"])
    opening = f"CLIP 표본 최빈 분류 · {LABELS[openings.most_common(1)[0][0]]}" if openings else ""
    region = text_regions.most_common(1)[0][0] if sum(text_regions.values()) else "bottom"
    subtitle_notes = "OCR에서 관찰한 화면 글자의 최빈 영역을 초안에 반영했습니다." if sum(text_regions.values()) else ""
    return {
        "profile_id": uid(), "name": "내 편집 스타일",
        "opening_style": opening, "avg_shot_length": average,
        "preferred_sequence": [], "subtitle_style": {"position": region, "notes": subtitle_notes},
        "pacing": f"전환 후보 {sum(len(item['cuts']) for item in evidence)}개 · 평균 컷 {average:g}초",
        "summary": "", "evidence": evidence, "approved_at": None,
    }


def profile_from_input(value, evidence):
    value = record(value, "스타일")
    style = record(value.get("subtitle_style", {}), "자막 스타일")
    position = style.get("position", "bottom")
    if position not in ("top", "middle", "bottom"):
        raise ReelMateError("스타일의 자막 위치를 선택하세요.")
    sequence = value.get("preferred_sequence", [])
    if not isinstance(sequence, list) or len(sequence) > 12 or any(
        not isinstance(label, str) or label not in LABELS for label in sequence
    ):
        raise ReelMateError("선호 장면 순서를 확인하세요.")
    profile = {
        "name": string(value.get("name"), "스타일 이름", 60),
        "opening_style": string(value.get("opening_style", ""), "오프닝 스타일", 200, allow_empty=True),
        "avg_shot_length": number(value.get("avg_shot_length"), "평균 컷 길이", 0.1, 120),
        "preferred_sequence": sequence,
        "subtitle_style": {
            "position": position,
            "notes": string(style.get("notes", ""), "자막 메모", 250, allow_empty=True),
        },
        "pacing": string(value.get("pacing", ""), "템포 메모", 200, allow_empty=True),
        "summary": string(value.get("summary", ""), "스타일 요약", 600, allow_empty=True),
        "evidence": evidence,
    }
    return profile


@lru_cache(maxsize=1)
def load_whisper(model):
    if not whisper_available():
        raise ReelMateError("Whisper 의존성을 설치한 뒤 서버를 다시 시작하세요.")
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model

    cache = ROOT / ".tools" / "models" / "whisper-local" / sha256(model.encode()).hexdigest()[:16]
    if not all((cache / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
        # A local download directory also works on Windows accounts without symlink privileges.
        download_model(model, output_dir=str(cache), use_auth_token=False)
    return WhisperModel(str(cache), device="cpu", compute_type="int8", cpu_threads=min(4, os.cpu_count() or 1))


def transcribe(asset, directory):
    model_name = whisper_model_name()
    if not asset["has_audio"]:
        raise ReelMateError("이 원본에는 음성 트랙이 없습니다. 자막을 직접 입력하세요.")
    import numpy as np

    raw = run("ffmpeg", ["-v", "error", "-nostdin", *INPUT_OPTIONS, "-i", directory / asset["path"],
                         "-map", "0:a:0", "-t", asset["duration"], "-ac", 1, "-ar", 16000,
                         "-f", "f32le", "-"]).stdout
    if not raw:
        return {"model": f"faster-whisper/{model_name}", "segments": []}
    try:
        samples = np.frombuffer(raw, dtype="<f4")
        chunks, _ = load_whisper(model_name).transcribe(samples, vad_filter=True, beam_size=3)
        results = []
        for chunk in chunks:
            start, end = round(chunk.start, 3), min(round(chunk.end, 3), asset["duration"])
            text = chunk.text.strip()
            if end > start and text:
                results.append({"start": start, "end": end, "text": text})
    except ReelMateError:
        raise
    except Exception as exc:
        raise ReelMateError("Whisper 전사에 실패했습니다. 최초 가중치 다운로드와 설치를 확인하세요.") from exc
    return {"model": f"faster-whisper/{model_name}", "segments": results}
