import os
from pathlib import Path

import pytest

from reelmate.analysis import clip_segments, read_brief, transcribe
from reelmate.common import ReelMateError


def test_brand_guide_unicode_and_limits(tmp_path):
    guide = tmp_path / "guide.txt"
    guide.write_bytes("제품 노출 3초 이내".encode("cp949"))
    assert read_brief(guide) == "제품 노출 3초 이내"
    guide.write_text(" " * 10, encoding="utf-8")
    with pytest.raises(ReelMateError, match="본문"):
        read_brief(guide)


@pytest.mark.skipif(os.getenv("REELMATE_TEST_MODELS") != "1", reason="requires cached CLIP weights")
def test_actual_clip_inference(project, media_samples, tmp_path):
    project.upload(media_samples[:1])
    asset = project.data["assets"][0]
    segments = clip_segments(asset, project.directory, tmp_path, "analysis")
    assert segments[0]["start"] == 0
    assert segments[-1]["end"] == asset["duration"]
    assert all(s["model"] and -1 <= s["similarity"] <= 1 for s in segments)
    assert all(s["samples"] and not s["human_verified"] for s in segments)
    assert all((tmp_path / Path(s["thumbnail"]).name).is_file() for s in segments)


@pytest.mark.skipif(not os.getenv("REELMATE_TEST_SPEECH"), reason="requires a real speech video and Whisper weights")
def test_actual_whisper_transcription(project):
    project.upload([Path(os.environ["REELMATE_TEST_SPEECH"])])
    asset = project.data["assets"][0]
    result = transcribe(asset, project.directory)
    assert result["model"].startswith("faster-whisper")
    assert result["segments"]
    assert all(0 <= row["start"] < row["end"] <= asset["duration"] and row["text"]
               for row in result["segments"])
