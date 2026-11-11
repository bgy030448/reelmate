# ReelMate

ReelMate는 완성 릴스에서 개인 편집 스타일을 저장하고, 협찬 촬영 원본을 컷과 자막으로 구성하는 Windows 로컬 작업 공간입니다. React 화면이 Streamlit과 Python 편집 엔진에 연결됩니다.

## Windows에서 실행

이 폴더에 `.venv`가 준비되어 있으면 PowerShell에서 바로 시작할 수 있습니다. `streamlit_reelmate.py`는 저장소의 `frontend/dist/` React 빌드와 `frontend/streamlit.css`를 사용합니다. 앱 실행에는 Node.js가 필요하지 않습니다.

```powershell
Set-Location C:\reelmate
.\start_windows.cmd
```

브라우저에서 [ReelMate 로컬 작업 공간](http://127.0.0.1:8501)을 여세요. 실행한 창에서 `Ctrl+C`를 누르면 서버가 종료됩니다.

새 환경에서는 Python 3.12를 설치한 뒤 아래 명령을 실행하세요. FFmpeg와 ffprobe를 찾지 못하면 설치 스크립트가 프로젝트의 `.tools\ffmpeg`에 Windows 바이너리를 받습니다. React 화면을 다시 빌드할 때는 Node.js와 npm이 필요합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1
# React 화면을 수정했거나 빌드 결과가 필요할 때
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -Rebuild
```

Python 경로를 직접 지정하려면 `-Python` 인수를 사용하세요. 별도 FFmpeg 설치를 사용하려면 `REELMATE_FFMPEG_BIN`에 `ffmpeg.exe`와 `ffprobe.exe`가 들어 있는 폴더를 지정할 수 있습니다. Windows 미리보기는 맑은 고딕 Bold를 사용합니다. 다른 한글 글꼴은 `REELMATE_FONT`로 지정하세요. [FFmpeg 다운로드](https://www.ffmpeg.org/download.html)

React 원본은 `frontend/src/`에 있고 HTML 템플릿은 `frontend/index.html`입니다. 원본을 수정하면 `-Rebuild`로 빌드하고 `frontend/dist/`의 결과도 함께 반영하세요.

## 작업 순서

1. **프로젝트**에서 브랜드, 제품, 목표 길이, 비율을 설정합니다. 승인된 스타일이 있으면 선택할 수 있습니다.
2. **자료**에서 촬영 원본, 완성 레퍼런스, PDF·TXT 가이드를 따로 등록합니다. 텍스트 가이드는 직접 입력할 수 있습니다. 가이드 원문을 대조해 브랜드 규칙을 저장하고 승인합니다.
3. **분석**에서 촬영 원본의 장면 후보를 확인합니다. 필요한 장면 구간을 좁힌 뒤 라벨을 확인하거나 후보를 제외합니다. 완성 레퍼런스 1편 이상을 등록하면 컷 전환 후보와 평균 컷 길이를 측정할 수 있습니다. CLIP·OCR을 함께 쓰거나 첫 제품 노출과 자막 특성을 직접 기록한 뒤 스타일 프로필을 승인하세요. 스타일은 JSON으로 저장·가져올 수 있습니다.
4. **검토**에서 컷을 직접 추가하거나 수동 초안으로 시작합니다. 컷 순서와 원본 시간을 수정하고 자막 문구·시간·위치를 저장합니다. 컷 잠금과 같은 길이의 선택 컷 교체를 지원합니다. 검수는 충족, 미충족, 직접 확인 필요로 구분합니다. 필수 장면은 사람이 확인한 라벨과 타임코드를 사용하며, 화면과 음성 조건은 직접 확인 근거를 기록합니다.
5. **내보내기**에서 저장된 버전의 MP4와 편집 패키지를 생성합니다. 대체 ZIP의 개별 MP4를 번호순으로 편집기에 배치하고 SRT를 따로 가져오세요. 컷시트 CSV, EDL JSON, 검수 JSON도 ZIP에 포함됩니다. CapCut 편집 프로젝트 ZIP은 Windows 9.x의 시험용 초안에 적용해 컷과 텍스트를 독립 트랙으로 구성합니다. 실제 앱에서 편집·저장·재열기는 검증 대기입니다. [CapCut 초안 준비 및 적용](docs/capcut-validation.md)

## 선택 기능

- **CLIP**은 실제 프레임을 분류하고 시간 범위·유사도·모델을 기록합니다. 모델은 최초 실행 시 내려받아 `.tools\models`에 보관합니다. 라벨은 사용자가 보정할 수 있습니다. [CLIP 모델 문서](https://huggingface.co/docs/transformers/model_doc/clip)
- **Whisper**는 오디오가 있는 원본에서 전사 구간을 추출합니다. 검토에서 `Whisper 자막 가져오기`를 누르면 사용 중인 컷의 타임라인으로 시간을 변환해 기존 자막과 겹치지 않는 초안을 추가합니다.
- **OCR**은 선택 기능입니다. `kor`와 `eng` 언어 데이터를 갖춘 Tesseract를 PATH에 추가하거나 `REELMATE_TESSERACT`에 실행 파일 경로를 지정합니다. 레퍼런스의 표본 프레임에 보이는 글자 영역을 기록합니다.
- **Gemini**는 가이드 규칙 구조화, 스타일 요약, 편집안 생성, 선택 컷 재편집에 사용합니다. 환경변수 또는 `.streamlit/secrets.toml`에 `GEMINI_API_KEY`와 `GEMINI_MODEL`을 설정한 뒤 서버를 재시작하세요. `.env.example`에는 변수명이 정리되어 있습니다. 해당 기능을 누르면 UI에 안내된 가이드 본문, 편집 메타데이터 또는 요청 텍스트가 Google API로 전송됩니다. 영상 파일은 로컬에서 처리됩니다. [Gemini API 레퍼런스](https://ai.google.dev/api/generate-content)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -AI -Whisper
```

## 입력과 저장 범위

| 항목 | 지원 범위 |
|---|---|
| 영상 | MP4·MOV·M4V·WebM, 개당 20MB·120초, 한 번에 최대 6개, 프로젝트 합계 100MB |
| 가이드 | PDF 또는 UTF-8/CP949 TXT, 최대 5MB, PDF 80페이지, 본문 50,000자. 스캔 PDF는 텍스트 입력 사용 |
| 편집안 | 목표 1~60초, 컷 최소 0.1초, 최대 컷 120개·자막 120개·규칙 100개 |
| 출력 | 30fps H.264/AAC MP4. 9:16 540×960, 16:9 960×540, 1:1 720×720. 편집 ZIP 최대 80MB |
| CapCut 시험용 프로젝트 | 자막을 합성하지 않은 전체 길이의 정규화 소스, 컷·독립 텍스트 타임라인. ZIP 최대 80MB |

`start_windows.cmd`는 개인용 모드로 127.0.0.1에 바인딩하고 `data`에 저장합니다. `REELMATE_DATA_DIR`로 저장 경로를 지정할 수 있습니다. 같은 저장 경로에는 서버 한 개를 실행하세요. 브라우저 새로고침이나 서버 재시작 후 내 프로젝트에서 작업과 출력 이력을 열 수 있습니다. 프로젝트 삭제를 선택하면 등록 자료, 편집안, 출력과 이력을 함께 지우며, 별도 저장된 스타일 프로필은 유지됩니다. 교체한 가이드나 이전 출력도 프로젝트 삭제 시 정리됩니다. 자동 보관 만료 기능은 없습니다.

## Streamlit Community Cloud 배포

Streamlit Community Cloud의 **Create app**에서 이 GitHub 저장소와 `main` 브랜치를 선택합니다. Main file path는 `streamlit_reelmate.py`, Python 버전은 `3.12`로 지정합니다. Cloud는 `packages.txt`에서 FFmpeg, 한글 글꼴과 OCR 언어 데이터를 설치하고, `requirements.txt`에서 CPU용 CLIP 및 Whisper 의존성을 설치합니다. 배포에는 `streamlit_reelmate.py`, `reelmate/`, `.streamlit/config.toml`, `requirements.txt`, `packages.txt`, `frontend/streamlit.css`, `frontend/dist/` 전체가 포함되어야 합니다.

Gemini를 사용하려면 앱의 **Settings → Secrets**에 `GEMINI_API_KEY`와 `GEMINI_MODEL`을 TOML 문자열로 등록합니다. CLIP과 Whisper 가중치는 각 기능을 처음 실행할 때 내려받습니다. 기본 실행은 세션별 저장 모드이며, 새 브라우저 세션에서는 별도 작업 공간이 열립니다. 결과 파일은 작업 중에 내려받으세요.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

CLIP 가중치가 준비됐으면 `REELMATE_TEST_MODELS=1`로 실제 추론 테스트를 포함할 수 있습니다. Whisper 검증은 `REELMATE_TEST_SPEECH`에 말소리가 담긴 짧은 로컬 MP4 경로를 지정하세요. 브라우저 테스트 `node tests/browser.mjs`는 Playwright가 필요합니다. `REELMATE_PLAYWRIGHT`에 로컬 패키지 경로를 설정하거나 Node에서 해석 가능한 위치에 설치하세요. 시스템 Edge를 사용하려면 `REELMATE_TEST_BROWSER`에 실행 파일 경로를 지정합니다. 테스트는 합성 자료와 `tmp` 아래 별도 저장 경로를 사용합니다.

기능별 구현 및 검증 범위는 [요구사항 상태표](docs/requirements-status.md)에 정리되어 있습니다.
