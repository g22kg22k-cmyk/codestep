# 코드스텝 (CodeStep) — Python & Rust 코딩 학습 데스크톱 프로그램

짧은 레슨, 퀴즈, 경험치, 연속 학습 방식에서 착안한 한국어 멀티 언어(Python · Rust) 코딩 학습 프로그램입니다. **Windows 네이티브 창에서 모든 학습 기능이 실행됩니다.** Tk 위젯으로 만들었으며 브라우저, 웹뷰, HTML 화면, 로컬 웹 서버를 사용하지 않습니다.

## 바로 실행하기

폴더 안의 **`CodeStep.exe`를 두 번 클릭**하세요(`start.bat`을 열어도 같아요). Python을 포함해 설치할 것이 없고, 폴더를 통째로 다른 PC에 복사해도 그대로 실행돼요. EXE 파일 하나만 따로 복사해도 됩니다. 직접 빌드하면 프로젝트 폴더의 `코드스텝.exe`와 `dist/CodeStep.exe`로 만들어집니다(아래 'EXE 다시 만들기'). Python 레슨·연습장은 Python 설치와 인터넷 연결 없이도 즉시 실행되며, Rust 실기·연습장은 PC에 설치된 로컬 `rustc` 컴파일러와 연동해 실행합니다. 창 오른쪽 위 닫기 버튼으로 종료합니다.

현재 버전은 **3.0.0 멀티 언어 데스크톱 버전**입니다.

## 학습 기능

- **Python + Rust 멀티 언어 커리큘럼**: 홈 화면에서 `전체 언어` / `Python` / `Rust` 트랙을 전환해 학습할 수 있어요. Python 22유닛(58레슨·248문제: 입문~고급 + 단계별 종합 중간 시험 4개 + 정처기·COS Pro·알고리즘 실전 기출)과 Rust 16유닛(40레슨·176문제: 입문~고급 + 단계별 종합 중간 시험 4개·소유권·트레이트·실전 코딩테스트 기출) 총 **38유닛, 98레슨, 424문제**를 제공합니다.
- **오류와 친해지기 (Python 입문 4번째 유닛)**: 오류 메시지 읽는 법, 자주 만나는 오류 5가지(SyntaxError · IndentationError · NameError · TypeError · ValueError) 고치기, print로 버그 찾기(디버깅) 3레슨. 실기 문제는 일부러 틀린 코드를 받아 오류 메시지를 따라 고치는 연습이에요.
- **자주 하는 실수**: Python·Rust 입문 레슨 30개에 모두 58가지 실수를 '이렇게 쓰면 → 화면에 나오는 오류 → 이렇게 고쳐요 → 이유' 순서로 보여 줘요. 오류 문구는 손으로 적은 것이 아니라 앱의 실제 실행기와 rustc로 돌려서 기록한 것이고, 실기 답안이 같은 실수로 틀리면 채점 결과에서 해당 항목을 바로 알려 줘요.
- **초보자용 오류 안내**: `else if`, 한글 자판 따옴표(“ ”), 숫자로 시작하는 변수 이름, 함수 인자 개수, 파일 모드, Rust의 `println` 느낌표·정수/실수 계산·`match` 빠진 갈래·`if` 조건 타입 등 초보자가 자주 만나는 오류에 원인과 해결 방법을 한국어로 알려 줘요.
- **실제 외부 프로그램·컴파일러 연동**: 각 실기 문제마다 작업 폴더의 실제 `.py` 또는 `.rs` 파일(`Documents\CodeStep_실습\...`)이 연결되며, **Python IDLE**, **VS Code**, **메모장**, **터미널(`python` / `rustc`)**에서 직접 코드를 입력하고 저장(`Ctrl+S`)하면 학습 앱이 변경을 즉시 감지해 자동 확인합니다.
- **실기 결과물 인식**: 콘솔 출력(`stdout`)뿐 아니라 함수 반환값 검증(`functionChecks`)과 생성된 결과 파일(`report.txt`, `summary.json` 등)의 존재·내용까지 인식하고 미리보기를 제공합니다.
- **실행 환경 자동 연동**: PC에 설치된 Python/IDLE(python.org 설치 프로그램과 Python 설치 관리자로 설치한 것 모두, 최신 버전 우선) 및 Rust(`rustc.exe` / `%USERPROFILE%\.cargo\bin`)를 우선 탐색해 연동하고, Python 미설치 환경에서도 내장 기본 실행기로 모든 Python 실기 기능을 실행합니다. (Rust 설치 권장 순서: `1) MSVC Build Tools -> 2) Rust(rustup)`)
- 객관식, 빈칸 채우기, 코드 순서 맞추기, 실제 코드 작성 실기 코딩.
- 레슨별 단계별 가이드, 멀티 예제, 힌트, 즉시 채점과 설명.
- 언어별 독립 잠금 해제 진도와 완료한 레슨 다시 풀기(홈/설정에서 모든 레슨 자유 열기 선택 가능).
- 일반 레슨 첫 완료 20 XP(만점 +5 XP, 재학습 5 XP), 단계별 중간 시험 첫 완료 40 XP(만점 +10 XP, 재학습 10 XP), 오답 복습 3 XP.
- 레슨마다 하트 5개(외부 파일 자동 저장 미리보기에서는 하트가 차감되지 않으며, 하트가 없어도 계속 연습할 수 있습니다).
- 오답 노트, 일일 목표, 연속 학습, 22개 배지.
- 코드 연습장: `Python (.py)` / `Rust (.rs)` 언어 전환, `practice.py` / `practice.rs` 파일 동기화, Python `>>>` 대화형 터미널 & `rustc` 컴파일 실행, 결과 파일 실시간 목록·미리보기, 문법 색상, 줄 번호, 입력값, Python 10개 + Rust 10개(총 20개) 예제, 초안 자동 저장. `Tab`은 공백 4칸, `Ctrl+Enter`는 실행입니다.
- 학습 기록을 JSON 파일로 내보내기/불러오기. 초기화·불러오기 전에 기존 기록을 자동 백업합니다.

## 기록 저장

진도와 설정은 `%LOCALAPPDATA%\CodeStep\progress.json`, 코드 초안은 같은 폴더의 `draft.json`에 저장합니다(기존 `%LOCALAPPDATA%\PyStep` 기록이 있으면 처음 실행 시 자동 이전됩니다). 완료하지 않은 레슨의 문제 위치는 저장하지 않습니다.

이전 브라우저 버전의 기록은 해당 버전의 설정에서 내보낸 JSON 파일을 새 프로그램의 **설정 → 기록 불러오기**에서 가져올 수 있습니다.

## 코드 실행 범위

Python 실기 문제와 연습장은 PC에 설치된 실제 Python(미설치 시 내장 기본 실행기)의 별도 프로세스로, Rust 실기 문제와 연습장은 PC에 설치된 로컬 `rustc --edition 2021` 컴파일러로 실행됩니다.

- 코드 한 번 실행 제한: 타임아웃 5초, 입력값 4,000자, 출력 64,000자, 메모리 256 MB(내장 기본 실행기 및 작업 프로세스 보호).
- 무한 반복 등으로 시간이 초과되어도 프로그램 창이 멈추지 않으며 5초 후 자동 중단됩니다.
- 기존 제한형 샌드박스(`code_executor.run_code`)도 단위 테스트용으로 유지됩니다.

## 소스 실행과 구조

소스로 실행하려면 Python 3.10 이상과 Tcl/Tk가 필요합니다. 아래 'EXE 다시 만들기'의 `setup-build-python.ps1`을 한 번 실행하면 프로젝트 폴더 안(`.build-python`)에 공식 Python이 준비되고, 그다음부터는 `start.bat`만 열면 됩니다.

`start.ps1`은 `CODESTEP_PYTHON`(또는 `PYSTEP_PYTHON`) → `.build-python\python.exe` → PATH의 `python` 순서로 Python을 찾습니다. Microsoft Store 바로가기(`WindowsApps\python.exe`)와 다른 프로그램에 딸린 Python은 쓰지 않습니다. 저장 폴더를 따로 지정하려면 `python desktop.py --data-dir ./my-progress`를 사용하세요.

| 파일 | 역할 |
| --- | --- |
| `desktop.py` | 네이티브 프로그램과 EXE 워커 진입점 |
| `native_app.py` | Tk 멀티 언어 학습 화면, Python·Rust 하이라이터, 외부 연동, 설정 |
| `python_bridge.py` | 시스템 Python/IDLE 탐색, 워크스페이스 동기화, 실기 결과물 검증 |
| `rust_bridge.py` | `rustc` 탐색, 한국어 컴파일 오류 안내, Rust 함수 검사 하네스 및 실행·터미널 연동 |
| `learning.py` | 언어별 진도, 보상, 배지, PyStep 기록 자동 이전 및 로컬 파일 저장 |
| `data/curriculum.json` | 38유닛(Python 22 + Rust 16), 98레슨, 424문제, 자주 하는 실수 58가지, 20개 연습장 예제 |
| `tools/refresh_pitfalls.py` | '자주 하는 실수'를 실제로 실행해 오류 문구를 기록(`--check`는 검사만) |
| `tools/audit_curriculum.py` | 모든 정답·시작 코드·예제·연습장 예제를 실제로 실행해 내용 오류를 찾는 전수 검사(약 2분) |
| `code_executor.py` | 비동기 워크스페이스/샌드박스 프로세스 실행기 |
| `runner.py` | 작업 폴더용 CPython 실행기 및 제한형 샌드박스 |
| `setup-build-python.ps1` | 빌드·소스 실행용 공식 Python 3.12.10을 `.build-python`에 준비 |
| `CodeStep.spec`, `build-exe.ps1` | 단일 EXE 빌드 |
| `tools/export_public.py` | 개인정보 검사를 거친 공개용(GitHub) 사본 만들기 |
| `native_selftest.py`, `tests/` | 학습 흐름, 외부 연동, Python/Rust 검증 및 실행 파일 테스트 |

공개용 사본은 `tools/export_public.py`로 만듭니다. 소스·학습 자료·테스트·빌드 스크립트와 실행 파일 `CodeStep.exe`를 복사하고, 빌드 폴더·내려받은 Python·캐시는 넣지 않습니다. 사용자 이름·홈 폴더·절대 경로·이메일 주소가 한 군데라도 있으면 내보내기를 멈추며, EXE는 압축된 내부 항목까지 하나씩 풀어서 검사합니다. 소스보다 오래된 EXE는 넣지 않으니, 소스를 고쳤다면 `build-exe.ps1`로 다시 빌드한 뒤 내보내세요.

## 검증

```powershell
.\.build-python\python.exe -m unittest discover -s tests -p 'test_*.py' -v
.\.build-python\python.exe desktop.py --self-test test-results/native-source-report.json
.\.build-python\python.exe tests/check_exe.py dist/CodeStep.exe
.\.build-python\python.exe tools/audit_curriculum.py . test-results/audit.json
```

네이티브 검사는 7개 상단 탭·Setup 카탈로그, Python·Rust 언어 전환, Python 커리큘럼·예제 전수 실행 및 Rust 레슨 완료·실습 파일 동기화·미설치 `rustc` 안내·종료 후 진도·초안 보존을 확인합니다. EXE 검사는 별도 폴더에 EXE 하나만 복사하고 Python이 없는 PATH에서 두 번 실행합니다: 한 번은 Python이 전혀 없는 초보자 PC처럼(`CODESTEP_FORCE_EMBEDDED_PYTHON=1`, 내장 실행기), 한 번은 PC에 설치된 Python을 연동한 상태로요. 사용자 학습 기록은 건드리지 않고 임시 폴더를 사용합니다.

학습 내용(`data/curriculum.json`)을 고쳤다면 `tools/refresh_pitfalls.py`로 '자주 하는 실수'의 오류 문구를 다시 기록하고, `tools/audit_curriculum.py`로 정답·예제가 실제로 맞는지 확인하세요. 오류 안내 문구(`runner.py`, `rust_bridge.py`)를 바꿨을 때도 `refresh_pitfalls.py`를 다시 실행해야 단위 테스트가 통과해요.

## EXE 다시 만들기

빌드하는 PC에 Python을 설치할 필요는 없습니다. 처음 한 번만 아래 첫 줄을 실행하세요. python.org에서 공식 Python 3.12.10 구성요소 4개(약 14 MB)를 받아 크기와 Python Software Foundation 서명을 확인한 뒤 `.build-python` 폴더에 풉니다. 시스템에 설치하거나 레지스트리·PATH를 바꾸지 않으므로 프로젝트 폴더를 옮겨도 그대로 동작합니다. 이어서 PyPI에서 `requirements-build.txt`의 PyInstaller를 그 안에 설치합니다. 프로젝트 자료는 어디에도 업로드하지 않습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup-build-python.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-exe.ps1
```

3.12.10은 Windows용 파일이 있는 마지막 3.12 버전입니다(이후 3.12 버전은 소스만 배포). 중간에 끊겨 반쯤 풀린 폴더는 다음 실행 때 자동으로 지우고 처음부터 다시 받습니다.

결과는 `dist/CodeStep.exe`와 프로젝트 루트의 `코드스텝.exe`입니다. EXE에는 CPython, Tcl/Tk, 학습 데이터, 아이콘, 원본 라이선스 고지가 포함됩니다. `THIRD_PARTY_LICENSES.txt`는 배포 구성요소의 필수 라이선스 고지입니다.

## 라이선스

코드스텝의 소스 코드와 학습 자료는 [MIT 라이선스](LICENSE)로 공개합니다. 저작권 표시와 라이선스 문구만 함께 남기면 자유롭게 사용·수정·배포할 수 있습니다. EXE에 함께 들어가는 Python, Tcl/Tk 등 다른 구성요소는 각자의 라이선스를 따르며 `THIRD_PARTY_LICENSES.txt`에 고지되어 있습니다.
