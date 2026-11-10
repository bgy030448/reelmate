"""Check or install a ReelMate CapCut package into a dedicated Windows test draft."""

import argparse
import hashlib
import os
import re
import subprocess
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from .capcut import CAPCUT_FORMAT
from .capcut_draft import TEXT_Y, compile_draft, load_draft, plain_object
from .common import ASPECTS, FPS, ROOT, ReelMateError, atomic_json, atomic_write, file_name, items, record, string, uid
from .exporter import ZIP_LIMIT


MARKER = ".reelmate-installed.json"
LOCK = ".reelmate-installing"
MANIFEST_LIMIT = 512 * 1024


def whole_number(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ReelMateError(f"CapCut 패키지의 {name} 값이 올바르지 않습니다.")
    return value


def read_package(archive):
    entries = archive.infolist()
    names = archive.namelist()
    if len(names) > 122 or len(set(names)) != len(names) or "manifest.json" not in names:
        raise ReelMateError("ReelMate CapCut 패키지의 ZIP 목록이 올바르지 않습니다.")
    if sum(item.file_size for item in entries) > ZIP_LIMIT:
        raise ReelMateError("CapCut 패키지의 압축 해제 크기는 80MB 이하만 지원합니다.")
    if archive.getinfo("manifest.json").file_size > MANIFEST_LIMIT:
        raise ReelMateError("CapCut 패키지 매니페스트가 너무 큽니다.")
    manifest = plain_object(archive.read("manifest.json"), "CapCut 패키지 매니페스트")
    if manifest.get("format") != CAPCUT_FORMAT or type(manifest.get("fps")) is not int or manifest["fps"] != FPS:
        raise ReelMateError("ReelMate의 CapCut 프로젝트 ZIP을 선택하세요.")
    whole_number(manifest.get("plan_version"), "편집안 버전", 1, 1_000_000)
    total = whole_number(manifest.get("duration"), "타임라인 길이", FPS, 60 * FPS)
    width = whole_number(manifest.get("width"), "너비", 1, 960)
    height = whole_number(manifest.get("height"), "높이", 1, 960)
    if (width, height) not in ASPECTS.values():
        raise ReelMateError("CapCut 패키지의 화면 비율이 올바르지 않습니다.")

    sources = items(manifest.get("sources"), "CapCut 소스", 120)
    if not sources:
        raise ReelMateError("CapCut 패키지에 영상 소스가 없습니다.")
    expected = {"manifest.json", "README.txt"}
    for index, source in enumerate(sources, 1):
        source = record(source, "CapCut 소스")
        file_name(source.get("name"))
        whole_number(source.get("frames"), "소스 길이", 3, 120 * FPS)
        whole_number(source.get("bytes"), "소스 크기", 1, ZIP_LIMIT)
        digest = source.get("sha256")
        if type(source.get("has_audio")) is not bool or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReelMateError("CapCut 영상 소스의 정보 또는 해시가 올바르지 않습니다.")
        expected.add(f"media/source-{index:03d}.mp4")
    if set(names) != expected:
        raise ReelMateError("CapCut 패키지의 영상 파일 목록이 매니페스트와 다릅니다.")
    if any(archive.getinfo(f"media/source-{i:03d}.mp4").file_size != src["bytes"]
           for i, src in enumerate(sources, 1)):
        raise ReelMateError("CapCut 패키지의 영상 파일 크기가 매니페스트와 다릅니다.")

    cursor = 0
    for cut in items(manifest.get("clips"), "CapCut 컷", 120):
        cut = record(cut, "CapCut 컷")
        asset = sources[whole_number(cut.get("source"), "소스 번호", 1, len(sources)) - 1]
        start = whole_number(cut.get("in"), "소스 인점", 0, asset["frames"] - 3)
        length = whole_number(cut.get("frames"), "컷 길이", 3, asset["frames"] - start)
        at = whole_number(cut.get("at"), "타임라인 위치", 0, total - 3)
        if at != cursor:
            raise ReelMateError("CapCut 컷 사이에 타임라인이 겹치거나 비어 있습니다.")
        cursor += length
    if cursor != total:
        raise ReelMateError("CapCut 타임라인의 길이와 컷 길이의 합이 다릅니다.")

    previous_end = 0
    for caption in items(manifest.get("subtitles"), "CapCut 자막", 120):
        caption = record(caption, "CapCut 자막")
        string(caption.get("text"), "CapCut 자막 문구", 140)
        start = whole_number(caption.get("start"), "자막 시작", previous_end, total - 1)
        previous_end = whole_number(caption.get("end"), "자막 종료", start + 1, total)
        if not isinstance(caption.get("position"), str) or caption["position"] not in TEXT_Y:
            raise ReelMateError("CapCut 패키지의 자막 위치가 올바르지 않습니다.")
    return manifest


def verify_media(archive, manifest, output=None):
    for index, source in enumerate(manifest["sources"], 1):
        filename = f"source-{index:03d}.mp4"
        destination = (output / filename).open("xb") if output is not None else nullcontext()
        with destination as target, archive.open(f"media/{filename}") as handle:
            digest = hashlib.sha256()
            size = 0
            while chunk := handle.read(256 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if target is not None:
                    target.write(chunk)
        if not size or digest.hexdigest() != source["sha256"]:
            raise ReelMateError("CapCut 패키지에 손상된 영상 파일이 있습니다. ReelMate에서 다시 내려받으세요.")


def capcut_running():
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq CapCut.exe", "/FO", "CSV", "/NH"],
        check=True, capture_output=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return b'"capcut.exe",' in result.stdout.lower()


def ensure_closed(folder, check_process=False):
    if (folder / ".locked").exists() or (check_process and capcut_running()):
        raise ReelMateError("CapCut을 완전히 종료한 다음 다시 실행하세요.")


def apply_install(archive, manifest, folder, media_dir, changes, snapshots, backup_root, build):
    lock = folder / LOCK
    try:
        lock.touch(exist_ok=False)
    except FileExistsError as exc:
        raise ReelMateError("이 초안에 진행 중이거나 중단된 적용 기록이 있습니다. 백업 상태를 확인하세요.") from exc
    try:
        with TemporaryDirectory(prefix=".reelmate-stage-", dir=folder) as staging:
            staged_media = Path(staging) / "media"
            staged_media.mkdir()
            verify_media(archive, manifest, staged_media)
            ensure_closed(folder, check_process=True)
            if any(path.resolve() != path or path.read_bytes() != raw for path, raw in snapshots.items()):
                raise ReelMateError("검사 중 시험용 초안이 변경되었습니다. CapCut을 닫고 다시 검사하세요.")
            if media_dir.exists() or (folder / MARKER).exists():
                raise ReelMateError("이 시험용 초안에 이미 ReelMate 출력이 있습니다. 새 시험용 초안을 준비하세요.")

            backup = backup_root / f"capcut-v{manifest['plan_version']}-{uid()[:12]}"
            backup.mkdir(parents=True, exist_ok=False)
            for path in changes:
                atomic_write(backup / path.relative_to(folder), snapshots[path])
            atomic_json(backup / "reelmate-backup.json", {
                "build": build, "version": manifest["plan_version"], "media": media_dir.name,
                "files": [path.relative_to(folder).as_posix() for path in changes],
            })
            os.replace(staged_media, media_dir)
            applied = []
            try:
                for path, document in changes.items():
                    atomic_json(path, document)
                    applied.append(path)
                atomic_json(folder / MARKER, {"build": build, "version": manifest["plan_version"]})
            except BaseException:
                try:
                    for path in reversed(applied):
                        atomic_write(path, snapshots[path])
                    os.replace(media_dir, staged_media)
                except OSError as exc:
                    raise ReelMateError(f"적용을 자동으로 되돌리지 못했습니다. 백업 폴더에서 복원하세요. {backup}") from exc
                raise
            return backup
    finally:
        lock.unlink(missing_ok=True)


def install(bundle, draft, build, *, apply=False, backup_root=None):
    bundle = Path(bundle)
    requested = Path(os.path.abspath(draft))
    folder = requested.resolve()
    if folder != requested or not folder.is_dir():
        raise ReelMateError("CapCut이 만든 실제 시험용 초안 폴더를 지정하세요.")
    if (folder / MARKER).exists() or (folder / LOCK).exists():
        raise ReelMateError("이미 사용했거나 적용 중인 초안입니다. 새 ReelMate Test 초안을 준비하세요.")
    ensure_closed(folder)
    if not bundle.is_file() or bundle.stat().st_size > ZIP_LIMIT:
        raise ReelMateError("80MB 이하의 ReelMate CapCut 프로젝트 ZIP을 지정하세요.")
    with ZipFile(bundle) as archive:
        manifest = read_package(archive)
        doc, meta, virtual, mirrors, snapshots = load_draft(folder, build)
        media_dir = folder / f"reelmate-media-v{manifest['plan_version']}"
        if media_dir.exists() or media_dir.is_symlink():
            raise ReelMateError("이 초안에 같은 버전의 미디어 폴더가 이미 있습니다.")
        doc, meta, virtual = compile_draft(doc, meta, virtual, manifest, media_dir)
        changes = {path: doc for path in mirrors}
        changes[folder / "draft_meta_info.json"] = meta
        if virtual is not None:
            changes[folder / "draft_virtual_store.json"] = virtual
        backup = None
        if apply:
            backups = Path(backup_root) if backup_root is not None else ROOT / "data" / "capcut-backups"
            backup = apply_install(archive, manifest, folder, media_dir, changes, snapshots, backups, build)
        else:
            verify_media(archive, manifest)
        return {
            "build": build, "schema": doc["new_version"], "version": manifest["plan_version"],
            "clips": len(manifest["clips"]), "subtitles": len(manifest["subtitles"]),
            "files": [path.relative_to(folder).as_posix() for path in changes], "backup": backup,
        }


def main():
    parser = argparse.ArgumentParser(description="ReelMate Windows CapCut 프로젝트 초안 적용")
    parser.add_argument("package", help="ReelMate에서 내려받은 CapCut 프로젝트 ZIP")
    parser.add_argument("--draft", required=True, help="CapCut에서 만든 ReelMate Test 초안 폴더")
    parser.add_argument("--build", required=True, help="CapCut Desktop 전체 빌드 번호")
    parser.add_argument("--apply", action="store_true", help="검사 결과를 시험용 초안에 적용합니다.")
    args = parser.parse_args()
    if os.name != "nt":
        parser.exit(2, "이 명령은 Windows CapCut Desktop용입니다.\n")
    try:
        result = install(args.package, args.draft, args.build, apply=args.apply)
    except ReelMateError as exc:
        parser.exit(2, f"CapCut 적용 중단 · {exc}\n")
    except (BadZipFile, RuntimeError, NotImplementedError):
        parser.exit(2, "CapCut 적용 중단 · ZIP이 손상되었거나 지원되지 않는 형식입니다.\n")
    except (OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"CapCut 적용 중단 · 로컬 파일과 CapCut 종료 상태를 확인하세요. {exc}\n")
    print(f"CapCut {result['build']} · 스키마 {result['schema']} · 편집안 v{result['version']}")
    print(f"컷 {result['clips']}개 · 독립 자막 {result['subtitles']}개")
    print("\n".join(f"  {filename}" for filename in result["files"]))
    if result["backup"]:
        print(f"시험용 초안에 적용했습니다. 백업 위치 {result['backup']}")
    else:
        print("검사만 완료했습니다. 실제 적용은 같은 명령에 --apply를 붙여 실행하세요.")


if __name__ == "__main__":
    main()
