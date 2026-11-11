r"""ReelMate Streamlit 화면과 앱 연결 코드.

ReelMate 폴더에서 실행합니다.
    .\.venv\Scripts\python.exe -m streamlit run streamlit_reelmate.py

개인용 저장 모드는 실행 전에 REELMATE_SINGLE_USER=1을 설정합니다.
frontend/dist의 React 빌드를 연결하며, 영상 처리와 모델 추론은 기존 reelmate 패키지를 호출합니다.
모델 구현과 실행 예시는 reelmate.ipynb에 정리되어 있습니다.
"""

import logging
import os
from pathlib import Path

import streamlit as st
from streamlit import runtime
from streamlit.components.v1 import declare_component

from reelmate.ai import Gemini
from reelmate.capcut import CAPCUT_FILENAME
from reelmate.common import ASPECTS, LABELS, ROOT, RULE_TYPES, ReelMateError, object_id, record, uid
from reelmate.exporter import OUTPUT_FILES
from reelmate.service import Service
from reelmate.validation import validate


LOG = logging.getLogger("reelmate")
WIDGET = "reelmate_ui"
FRONTEND = Path(__file__).resolve().parent / "frontend"
st.set_page_config(page_title="ReelMate", page_icon="🎬", layout="wide")
st.html(FRONTEND / "streamlit.css")


def config_value(key):
    if os.environ.get(key):
        return os.environ[key]
    try:
        value = st.secrets.get(key, "")
        return value if isinstance(value, str) else ""
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


@st.cache_resource(validate=lambda cached: type(cached) is Service)
def open_service(path, _gemini_key, model):
    return Service(path, Gemini(_gemini_key, model))


local_mode = os.environ.get("REELMATE_SINGLE_USER") == "1"
root = Path(os.environ.get("REELMATE_DATA_DIR") or ROOT / "data").resolve()
if not local_mode:
    if "workspace_session" not in st.session_state:
        st.session_state.workspace_session = uid()
    root = root / "sessions" / st.session_state.workspace_session

# The key stays in the Python process. A key change takes effect on server restart.
service = open_service(str(root), config_value("GEMINI_API_KEY"), config_value("GEMINI_MODEL"))

if "active_project" not in st.session_state:
    st.session_state.active_project = None
    requested = st.query_params.get("project")
    if requested:
        try:
            st.session_state.active_project = service.project(requested)["project_id"]
        except ReelMateError:
            st.query_params.pop("project", None)


def activate(project_id):
    if st.session_state.active_project == project_id:
        return
    st.session_state.active_project = project_id
    st.session_state.pop("selected_version", None)
    st.session_state.pop("selected_capcut_version", None)
    st.session_state.pop("selected_asset", None)
    if project_id:
        st.query_params["project"] = project_id
    else:
        st.query_params.pop("project", None)


def on_event():
    event = st.session_state.get(WIDGET)
    if not isinstance(event, dict):
        return
    event_id = event.get("id")
    if not isinstance(event_id, str) or len(event_id) > 80 or event_id == st.session_state.get("last_event"):
        return
    st.session_state.last_event = event_id
    action = event.get("action")
    ack = {"id": event_id, "ok": False}
    try:
        body = record(event.get("body", {}), "요청")
        project_id = st.session_state.active_project
        if action == "project_open":
            activate(service.project(body.get("project_id"))["project_id"])
            result = {"message": "저장한 프로젝트를 열었습니다."}
        elif action in ("output_select", "capcut_select", "asset_select"):
            project = service.project(project_id)
            if action == "asset_select":
                asset_id = object_id(body.get("asset_id"), "원본")
                if not any(a["asset_id"] == asset_id for a in project["assets"]):
                    raise ReelMateError("영상을 찾을 수 없습니다.")
                st.session_state.selected_asset = asset_id
            else:
                version = body.get("version")
                exports, selection = ("outputs", "selected_version") if action == "output_select" else (
                    "capcut_exports", "selected_capcut_version")
                if type(version) is not int or not any(o["version"] == version for o in project.get(exports, [])):
                    raise ReelMateError("출력 버전을 찾을 수 없습니다.")
                st.session_state[selection] = version
            result = {"message": ""}
        else:
            if not isinstance(action, str):
                raise ReelMateError("지원되지 않는 요청입니다.")
            if action not in {"project_create", "profile_import", "profile_save"} and event.get("project_id") != project_id:
                raise ReelMateError("현재 열린 프로젝트를 확인하세요.")
            result = service.dispatch(action, body, project_id, event.get("revision"))
            if "project_id" in result:
                activate(result["project_id"])
            if "output_version" in result:
                st.session_state.selected_version = result["output_version"]
            if "capcut_version" in result:
                st.session_state.selected_capcut_version = result["capcut_version"]
        ack.update(ok=True, **result)
    except ReelMateError as exc:
        ack["message"] = str(exc)
    except Exception:
        LOG.exception("A ReelMate operation failed.")
        ack["message"] = "작업을 저장하지 못했습니다. 연결과 저장 공간을 확인한 뒤 다시 시도하세요."
    st.session_state.ack = ack


def media_link(directory, relative, mime, key, filename=None):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory) or not path.is_file() or not runtime.exists():
        return None
    try:
        return runtime.get_instance().media_file_mgr.add(
            str(path), mime, f"reelmate.{key}", file_name=filename, is_for_static_download=filename is not None,
        )
    except OSError:
        return None


def public_project(project_id):
    if not project_id:
        return None
    try:
        project = service.project(project_id)
    except ReelMateError:
        return None
    directory = service.directory(project_id)
    assets = []
    selected_asset = st.session_state.get("selected_asset")
    source_types = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
    for entry in project["assets"]:
        asset_id = entry["asset_id"]
        asset = {key: value for key, value in entry.items()
                 if key not in {"path", "thumbnail", "video_index", "subtitle_index"}}
        asset["thumbnail_url"] = media_link(directory, entry["thumbnail"], "image/jpeg", asset_id)
        if selected_asset == asset_id:
            mime = source_types.get(Path(entry["path"]).suffix, "video/mp4")
            asset["preview_url"] = media_link(directory, entry["path"], mime, "inspect")
        assets.append(asset)
    segments = []
    for entry in project["segments"]:
        segments.append({key: value for key, value in entry.items() if key != "thumbnail"} | {
            "thumbnail_url": media_link(directory, entry["thumbnail"], "image/jpeg", entry["segment_id"]),
        })

    outputs = [{key: value for key, value in output.items() if key != "directory"}
               for output in reversed(project["outputs"])]
    latest = max((item["version"] for item in outputs), default=None)
    chosen_version = st.session_state.get("selected_version", latest)
    chosen = next((item for item in project["outputs"] if item["version"] == chosen_version), None)
    downloads = None
    if chosen:
        urls = {}
        for key, (name, mime, extension) in OUTPUT_FILES.items():
            url_name = "편집안" if key == "plan" else key
            urls[key] = media_link(directory, f"{chosen['directory']}/{name}", mime, key,
                                   f"ReelMate-v{chosen_version}-{url_name}.{extension}")
        urls["player"] = media_link(directory, f"{chosen['directory']}/preview.mp4", "video/mp4", "player")
        downloads = {"version": chosen_version, "urls": urls}
    native = sorted(project.get("capcut_exports", []), key=lambda item: item["version"], reverse=True)
    capcut_download = None
    if native:
        version = st.session_state.get("selected_capcut_version", native[0]["version"])
        selected = next((item for item in native if item["version"] == version), native[0])
        capcut_download = {
            "version": selected["version"],
            "url": media_link(directory, f"{selected['directory']}/{CAPCUT_FILENAME}", "application/zip",
                              "capcut-project", f"ReelMate-v{selected['version']}-CapCut.zip"),
        }
    guide = project["guide"]
    return {**project, "assets": assets, "segments": segments, "outputs": outputs,
            "capcut_exports": [{key: value for key, value in item.items() if key != "directory"} for item in native],
            "capcut_download": capcut_download,
            "guide": {key: guide[key] for key in ("text", "filename")} if guide else None,
            "validation": validate(project, directory), "downloads": downloads}


component = declare_component("studio", path=str(FRONTEND / "dist"))
component(key=WIDGET, on_change=on_event, state={
    "project": public_project(st.session_state.active_project),
    "projects": service.projects(),
    "profiles": service.profiles(),
    "capabilities": service.capabilities(),
    "labels": LABELS,
    "rule_types": RULE_TYPES,
    "aspects": ASPECTS,
    "local": local_mode,
    "ack": st.session_state.get("ack"),
})
