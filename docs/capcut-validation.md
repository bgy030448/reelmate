# Windows CapCut 프로젝트 검증

ReelMate의 **내보내기 → CapCut 편집 프로젝트**에서 저장된 편집안의 ZIP을 생성합니다. 전체 길이의 30fps H.264 MP4 소스와 컷·자막 타이밍이 들어 있습니다. 소스는 미리보기와 같은 비율로 중앙 크롭됩니다. 적용 도구가 CapCut 초안에 영상 구간과 독립 텍스트 객체를 생성합니다. 대체 ZIP도 개별 컷과 SRT를 가져오는 경로로 제공됩니다. [CapCut SRT 가져오기 안내](https://www.capcut.com/help/how-to-import-subtitles)

## 준비할 버전과 샘플

- **첫 검증 후보는 Windows CapCut Desktop 9.3.0.3970**입니다. 공개된 독립 도구가 이 빌드에서 수정한 로컬 초안을 열었습니다. 이미 Windows 9.x 정식 빌드를 쓰고 있다면 현재 빌드에서 새 샘플을 만드세요. ReelMate의 앱 내 호환 판정은 아래 절차를 실제로 통과한 빌드에 한정합니다. [9.3.0.3970 Windows 사례](https://github.com/spectrika/capcut-mcp/blob/main/CHANGELOG.md)
- **CapCut 설정 → 버전**의 전체 번호와 **winver**에 표시되는 Windows 버전·빌드를 기록하세요. CapCut 화면에 빌드 번호가 생략되면 작업 관리자에서 CapCut.exe의 파일 위치를 연 다음 **속성 → 자세히 → 파일 버전**을 확인합니다. [CapCut 버전 확인 안내](https://www.capcut.com/help/where-to-find-my-current-version-capcut)
- 색이나 내용이 다른 **6초 H.264 MP4 두 개**를 준비하세요. 9:16·30fps를 권장하며, 한 파일에 소리가 있으면 오디오도 확인할 수 있습니다. CapCut에서 **ReelMate Test**라는 새 로컬 프로젝트를 만들고 한 메인 트랙에 A와 B를 5초씩 배치합니다. 별도의 **기본 텍스트 트랙 하나**에 한글 텍스트 두 개를 겹치지 않게 놓습니다. 예를 들어 1~3초에 **제품 소개**, 6~8초에 **사용 장면**을 넣습니다. 기본 서식을 사용하고, 프로젝트 목록으로 돌아가 저장한 뒤 CapCut을 완전히 종료합니다. [CapCut 프로젝트 저장 안내](https://www.capcut.com/help/modify-history-task)
- CapCut의 초안 저장 위치에서 방금 만든 **개별 프로젝트 폴더**를 찾으세요. 기본 경로의 예시는 아래와 같습니다. 샘플을 전달할 때는 두 MP4와 해당 폴더의 **draft_meta_info.json**, **draft_content.json** 또는 **draft_info.json**, 그리고 **Timelines**, **template*.tmp**, **\*.bak**, **draft_virtual_store.json** 중 있는 항목을 준비하세요. 공유용 사본에서는 개인 경로와 장치 식별자를 가릴 수 있습니다. 적용은 CapCut이 등록한 실제 시험용 폴더에서 진행합니다. [Windows 초안 구조 조사](https://github.com/chuk-development/chukcut/blob/master/docs/research/draft-format.md)

    %LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft

적용 도구는 Windows 9.x의 평문 JSON과 단일 타임라인을 검사합니다. 10.x를 쓰고 있다면 해당 빌드에서 만든 같은 10초 샘플이 다음 호환 검증 대상입니다. 10.x 및 암호화된 초안은 현재 적용이 중단됩니다. [버전별 공개 관찰 기록](https://github.com/renezander030/capcut-cli/blob/master/docs/version-support.md)

## 검사 및 적용

1. ReelMate에서 같은 영상과 자막으로 10초 편집안을 저장합니다. 검수 후 **CapCut 프로젝트 ZIP 생성**을 눌러 내려받습니다.
2. PowerShell에서 ZIP, 시험용 초안 폴더, 빌드 번호를 자신의 값으로 바꿉니다. 아래 첫 명령은 파일과 타이밍을 검사하고 적용할 파일을 표시합니다.

~~~powershell
Set-Location C:\reelmate
$package = 'C:\Downloads\ReelMate-v2-CapCut.zip'
$draft = 'C:\CapCut Drafts\ReelMate Test'
$build = '9.3.0.3970'
.\.venv\Scripts\python.exe -m reelmate.capcut_install $package --draft $draft --build $build
~~~

3. 검사 결과에 컷 2개와 독립 자막 2개가 표시되면 같은 명령에 **--apply**를 붙입니다. 전용 초안의 루트와 활성 타임라인 복사본을 동기화하고 기존 프로젝트 ID와 등록 정보를 유지합니다. 백업 위치는 터미널에 표시됩니다. [빌드별 활성 타임라인 사례](https://github.com/renezander030/capcut-cli/issues/50)

~~~powershell
.\.venv\Scripts\python.exe -m reelmate.capcut_install $package --draft $draft --build $build --apply
~~~

## 열기·편집·저장·재열기

1. CapCut을 실행해 **ReelMate Test**를 엽니다. 미디어가 연결되고 메인 트랙의 컷 두 개와 텍스트 트랙의 자막 두 개를 따로 선택할 수 있는지 확인합니다.
2. 첫 자막을 **제품 소개 — 저장 확인**으로 바꾸고 시작 시간을 0.5초 옮깁니다. 두 번째 컷의 시작이나 끝을 조정합니다.
3. 프로젝트 목록으로 돌아가 저장하고 CapCut을 완전히 종료합니다. 다시 열어 컷 조정과 자막의 문구·시간이 유지되고 미디어와 한글이 표시되는지 확인합니다.
4. Windows 빌드, CapCut 전체 빌드, ReelMate 편집안 버전과 결과를 기록합니다. 오류가 있으면 CapCut 메시지와 재현 단계를 남깁니다.

이 PC에서는 CapCut 데스크톱 실행 파일을 찾지 못했습니다. 합성 초안의 트랙 구조·미디어 연결·백업·실패 시 복원을 포함한 Python 테스트 32개와 React 빌드를 통과했습니다. Edge에서 ZIP을 생성·다운로드하고, ReelMate 서버를 재시작한 뒤 같은 출력을 다시 받았습니다. GATE 1은 실제 CapCut에서 위 절차를 통과해야 완료됩니다.
