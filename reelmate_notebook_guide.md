# ReelMate 노트북 코드 설명

이 노트북은 협찬 릴스의 영상을 분석하고, 장면 후보와 브랜드 조건을 바탕으로 편집 초안을 만드는 모델 부분입니다. CLIP과 Whisper는 사전학습 가중치를 불러와 추론합니다. Gemini는 입력을 구조화하고 편집 초안을 생성합니다. [설명 대상 노트북](reelmate.ipynb)

코드 셀 번호는 설명용 마크다운 셀을 제외하고 위에서부터 센 순서입니다.

## 데이터가 흐르는 순서

- **촬영 영상**은 `VIDEO_PATHS`에서 불러와 `model_assets`로 정리합니다. CLIP이 만든 `scene_candidates`는 Gemini 편집안의 컷 후보로 들어갑니다.
- **완성 레퍼런스**는 `REFERENCE_PATHS`에서 불러옵니다. 컷 길이와 오프닝 등을 측정한 `style_profile`은 Gemini가 편집 스타일을 참고할 때 사용합니다.
- **브랜드 가이드**는 `GUIDE_PATH`에서 읽습니다. Gemini가 본문을 `rules` 목록으로 변환하고, 이를 컷 후보와 함께 사용해 `draft`를 생성합니다.
- **Whisper 전사**는 `model_assets`의 오디오에서 시작·종료 시각과 문구를 추출해 별도로 출력합니다.

## 1. 실행 환경 준비 (`setup`)

`subprocess.run()`으로 현재 노트북 커널의 Python에 패키지를 설치합니다. Pillow는 프레임 이미지를 읽고, pypdf는 PDF 본문을 추출합니다. PyTorch와 Transformers는 CLIP 모델과 입력 처리기를 불러오는 데 사용합니다.

| 설정 | 코드에서 하는 일 |
| --- | --- |
| `INSTALL_WHISPER` | `True`일 때 `faster-whisper`와 NumPy를 설치합니다. 기본값은 `False`입니다. |
| `INSTALL_OCR` | `True`이고 관리자 권한의 Linux에서 `apt-get`을 사용할 수 있으면 Tesseract와 한국어·영어 데이터 설치 목록을 추가합니다. 기본값은 `False`입니다. |
| FFmpeg·ffprobe | 같은 Linux 조건에서 실행 파일이 없으면 `ffmpeg` 패키지를 설치합니다. Windows에서는 다음 셀의 `executable()`이 설치 경로를 찾습니다. |

## 2. 공통 데이터와 함수 (`shared`)

| 이름 | 역할 |
| --- | --- |
| `ROOT` | 노트북 커널의 현재 폴더를 기준 경로로 정합니다. 모델 캐시와 ReelMate 폴더에 있는 FFmpeg를 찾을 때 사용합니다. |
| `LABELS` | `product`, `use`, `person` 같은 장면 키를 한국어 이름으로 연결합니다. CLIP 출력 표시와 Gemini 입력에 사용합니다. |
| `RULE_TYPES` | 필수 장면, 제품 노출 시점, 필수·금지 자막 문구, 길이, 직접 확인 등 브랜드 조건의 유형을 정의합니다. |
| `ReelMateError` | 영상 읽기, 추론, API 호출 등에 문제가 있을 때 이유를 전달하는 예외입니다. |
| `uid()` | 영상, 후보 구간, 스타일 프로필을 구분할 고유 ID를 만듭니다. |
| `string()` | 문자열의 앞뒤 공백을 정리하고 빈 값, 최대 길이, 널 문자 포함 여부를 검사합니다. |
| `json_text()` | 결과를 읽기 쉬운 들여쓰기와 한글을 유지한 JSON 문자열로 변환합니다. |

## 3. 영상 입력과 프레임 추출 (`input-processing`)

| 함수 또는 설정 | 입력과 결과 |
| --- | --- |
| `VIDEO_EXTENSIONS`, `INPUT_OPTIONS` | MP4·MOV·M4V·WebM 확장자와 FFmpeg·ffprobe에서 사용할 로컬 파일 및 컨테이너 옵션을 정의합니다. |
| `executable(name)` | `REELMATE_FFMPEG_BIN`, 시스템 PATH, `ROOT/.tools/ffmpeg` 순서로 실행 파일을 찾습니다. 지정한 환경변수 경로에 파일이 없으면 오류를 반환합니다. |
| `run(name, args, ...)` | FFmpeg 또는 ffprobe를 실행하고 표준 출력·오류를 캡처합니다. 시간 초과나 실행 실패는 `ReelMateError`로 전달합니다. |
| `probe(path)` | ffprobe의 JSON에서 길이, FPS, 해상도, 코덱, 회전, 오디오 유무와 영상·자막 스트림 번호를 읽습니다. 길이 0.1~120초, 240fps 이하, 최대 16,777,216화소 범위를 검사합니다. |
| `shot_boundaries(source, asset)` | 프레임 변화 점수가 `0.32`보다 큰 시점을 컷 후보로 찾습니다. 최소 간격 0.2초를 적용하고 영상의 시작과 끝을 포함한 시각 목록을 돌려줍니다. |
| `sample_frames(source, asset, directory, max_frames=36)` | 영상 길이에 맞춰 일정 간격으로 프레임을 추출합니다. 기본 최대 36장의 JPEG를 저장하고 경로 목록을 반환합니다. |
| `video_asset(path)` | 경로와 확장자를 검사한 뒤 고유 ID, 파일명, 경로, `probe()`의 메타데이터를 묶습니다. CLIP, 스타일 측정, Whisper가 같은 형식의 자료를 사용합니다. |

## 4. CLIP 모델과 장면 후보 생성 (`clip-model`)

| 이름 | 역할 |
| --- | --- |
| `CLIP_PROMPTS` | 오프닝, 제품 소개, 제품 사용, 인물, 공간 등 장면별 영문 설명을 정의합니다. 프레임과 비교할 텍스트 후보입니다. |
| `clip_model_name()` | `REELMATE_CLIP_MODEL`을 확인합니다. 기본 모델 ID는 `openai/clip-vit-base-patch32`입니다. |
| `clip_available()` | PyTorch와 Transformers를 사용할 수 있는지 확인합니다. |
| `load_clip(model_name)` | 로컬 캐시의 모델과 입력 처리기를 먼저 읽습니다. 필요하면 가중치를 내려받고, `eval()`로 추론 상태를 설정한 모델을 캐시에 보관합니다. |
| `classify_frames(paths, model_name)` | 이미지를 RGB로 읽고 장면 설명과 함께 최대 8장씩 모델에 넣습니다. `torch.inference_mode()`에서 계산한 점수 중 가장 유사한 장면의 키와 점수를 프레임마다 반환합니다. |
| `clip_segments(asset, directory, output, relative)` | 샘플 프레임을 분류한 뒤 같은 라벨이 연속되면 한 구간으로 묶습니다. 구간 ID, 시작·종료 시각, 라벨, 유사도, 개별 표본을 기록하고 가장 높은 유사도의 프레임을 대표 썸네일로 사용합니다. |

`similarity`는 CLIP의 `logits_per_image`를 `exp(logit_scale)`로 나눠 얻는 이미지·텍스트 코사인 유사도입니다. `start`와 `end`는 영상 길이를 표본 개수로 나눈 간격에 기반한 구간 시각입니다.

## 5. CLIP 실행 예시 (`clip-run`)

`VIDEO_PATHS`에 분석할 영상 경로를 넣습니다. `video_asset()`으로 `model_assets`를 만든 후 `clip_segments()`를 호출해 `scene_candidates`를 채웁니다. 화면에는 후보 구간의 시작·종료 시각, 한국어 라벨, 유사도를 출력합니다. 프레임과 썸네일은 실행 중 임시 폴더에서 처리합니다. 목록이 비어 있으면 경로 입력 안내를 표시합니다.

## 6. 편집 스타일 측정 (`style-model`)

- `PRODUCT_LABELS`는 제품 소개, 디테일, 사용, 패키지 장면을 제품 관련 후보로 묶습니다.
- `OCR_LANGUAGES`와 `ocr_executable()`은 한국어·영어 OCR을 설정하고, 환경변수 `REELMATE_TESSERACT` 또는 PATH에서 실행 파일을 찾습니다.
- `ocr_region(path)`는 이미지에서 신뢰도가 45 이상인 단어의 세로 위치를 구합니다. 단어 위치의 가운데 값을 바탕으로 프레임을 상단·중앙·하단 중 하나로 분류합니다. 조건을 충족하는 단어가 없으면 `None`을 반환합니다.
- `measure_style(assets, directory, ...)`는 완성 레퍼런스 3편 이상을 입력받습니다. 컷 경계에서 전체 컷의 평균 길이를 계산하고, 내장 텍스트 자막 트랙이 있으면 구간 수를 기록합니다. CLIP을 켜면 영상당 최대 16개 표본에서 오프닝 라벨과 첫 제품 관련 장면의 시각을 추정합니다. OCR을 켜면 화면 글자가 자주 나타나는 영역을 자막 위치의 참고값으로 기록합니다.

출력은 `avg_shot_length`, `opening_style`, `subtitle_style`, `pacing`, 영상별 관찰 기록 `evidence`가 담긴 스타일 프로필 초안입니다. 측정 직후 `approved_at`은 비어 있습니다.

## 7. 스타일 측정 실행 예시 (`style-run`)

`REFERENCE_PATHS`에 완성 릴스 경로를 넣고 `measure_style()`을 실행합니다. 예시 기본값은 `USE_CLIP_FOR_STYLE = True`, `USE_OCR_FOR_STYLE = False`입니다. 결과를 `style_profile`에 저장하고 JSON으로 출력합니다. 레퍼런스 경로를 입력하지 않으면 `style_profile`은 `None`으로 남습니다.

## 8. Whisper 음성 전사 (`whisper-model`)

| 함수 | 역할 |
| --- | --- |
| `whisper_model_name()` | `REELMATE_WHISPER_MODEL`을 읽습니다. 기본 모델은 `base`입니다. |
| `whisper_available()` | `faster_whisper`가 설치되어 있는지 확인합니다. |
| `load_whisper(model)` | 모델 파일을 캐시에서 읽거나 내려받고, CPU의 `int8` 추론 모드로 로드합니다. |
| `transcribe(asset, directory)` | FFmpeg로 첫 오디오 트랙을 16kHz 모노 `float32`로 변환합니다. Whisper의 음성 구간 검출을 켜고, 문구와 원본 영상 기준 `start`·`end`가 있는 자막 초안 목록을 반환합니다. |

## 9. Whisper 실행 예시 (`whisper-run`)

설치 셀에서 Whisper 의존성을 준비하고 `RUN_WHISPER`를 `True`로 바꿉니다. 5번 셀에서 만든 `model_assets`를 순회하며 오디오가 있는 영상만 전사합니다. 파일명과 전사 결과를 JSON으로 출력합니다.

## 10. Gemini 요청과 응답 처리 (`gemini-model`)

| 이름 | 역할 |
| --- | --- |
| `object_schema()` | 객체의 속성 및 필수 항목을 담은 JSON 스키마를 만듭니다. |
| `STR`, `NUM` | 스키마에서 재사용하는 문자열·숫자 타입 정의입니다. |
| `CLIP_SCHEMA`, `CAPTION_SCHEMA` | 컷의 후보 ID와 원본 시작·종료 시간, 자막의 문구와 타임라인 시작·종료 시간을 정의합니다. |
| `PLAN_SCHEMA`, `BRIEF_SCHEMA` | 편집안의 `clips`·`subtitles` 배열과 가이드의 `rules` 배열에 필요한 구조를 각각 정의합니다. |
| `Gemini.__init__()` | API 키와 모델 ID를 받아 요청 가능 여부를 설정합니다. |
| `Gemini.generate()` | 지시문, 입력 데이터, 응답 스키마를 Gemini API에 보냅니다. 정상 종료된 응답의 본문을 읽어 JSON 객체로 반환합니다. |
| `Gemini.parse_brief()` | 브랜드 가이드에서 필수 장면, 제한 시간, 문구 등의 규칙을 뽑습니다. 길이 조건의 값은 숫자로 변환을 시도합니다. |
| `Gemini.plan()` | 후보 구간, 브랜드 규칙, 편집 스타일을 받아 컷의 재생 순서와 자막을 포함한 초안을 요청합니다. 제공된 후보 ID와 시간만 사용하고 컷과 자막이 겹치지 않도록 지시합니다. |
| `Gemini.replace_clip()` | 사용 가능한 구간에서 지정한 길이를 유지하는 대체 컷 하나를 요청합니다. |
| `Gemini.summarize_style()` | 측정값과 관찰 기록을 바탕으로 한국어 스타일 요약을 요청합니다. |
| `read_brief(path)` | TXT는 UTF-8 또는 CP949로 읽고 PDF는 pypdf로 본문을 추출합니다. 잠긴 PDF, PDF 80페이지 초과, 본문 50,000자 초과 또는 빈 본문을 검사합니다. |

## 11. Gemini 실행 예시 (`gemini-run`)

1. `RUN_GEMINI`를 `True`로 바꿉니다. `GEMINI_API_KEY`와 `GEMINI_MODEL`을 환경변수에서 읽거나 실행 중 입력받습니다. API 키는 `getpass()`로 입력할 수 있습니다.
2. `GUIDE_PATH`가 있으면 가이드를 읽어 브랜드 규칙 `rules`를 생성하고 출력합니다. 경로가 비어 있으면 빈 규칙 목록을 사용합니다.
3. `scene_candidates`가 있으면 브랜드·제품명, 목표 길이, 화면 비율, 후보의 시간·라벨, 규칙과 선택적 `style_profile`을 보내 `draft`를 만듭니다. 기본 목표는 10초, 화면 비율은 `9:16`입니다.
4. `draft`의 `clips`에서 원본 영상의 사용할 구간을, `subtitles`에서 최종 영상에 배치할 자막의 문구와 시각을 확인할 수 있습니다.
