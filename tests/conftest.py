import base64
from pathlib import Path

import pytest

from reelmate.media import executable, run
from reelmate.service import Service


def encoded(path, name=None):
    return {"name": name or path.name, "data": base64.b64encode(path.read_bytes()).decode("ascii")}


@pytest.fixture(scope="session")
def media_samples(tmp_path_factory):
    try:
        executable("ffmpeg")
        executable("ffprobe")
    except ValueError as exc:
        pytest.skip(str(exc))
    root = tmp_path_factory.mktemp("videos")
    paths = []
    for index, color in enumerate(("red", "blue", "green")):
        path = root / f"원본 {index + 1}.mp4"
        sources = ["-f", "lavfi", "-i", f"color={color}:s=320x240:d=6:r=30"]
        if index == 0:
            sources.extend(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6"])
        run("ffmpeg", ["-v", "error", *sources, "-c:v", "libx264", "-c:a", "aac", "-shortest", path])
        paths.append(path)
    return paths


class Project:
    def __init__(self, directory, gemini=None):
        self.service = Service(Path(directory), gemini)
        self.settings = {"brand": "릴메이트", "product": "수분 크림", "target_duration": 10, "aspect_ratio": "9:16"}
        self.id = self.service.dispatch("project_create", self.settings)["project_id"]

    @property
    def data(self):
        return self.service.project(self.id)

    @property
    def directory(self):
        return self.service.directory(self.id)

    def do(self, action, **body):
        return self.service.dispatch(action, body, self.id, self.data["revision"])

    def upload(self, paths, role="source"):
        return self.do("upload", role=role, files=[encoded(path) for path in paths])

    def two_cuts(self):
        a, b, *_ = self.data["segments"]
        return [{"segment_id": s["segment_id"], "source_in": 0.5, "source_out": 5.5} for s in (a, b)]


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path / "data")
