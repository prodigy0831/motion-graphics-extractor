# 모션그래픽 추출기

AI 영상의 모션을 추출해 After Effects에서 재현하는 도구

영상에서 움직이는 객체의 좌표를 프레임별로 추출해,
After Effects에서 동일한 움직임을 가진 null object를 자동 생성하는 파이프라인.

## 전제 조건

- Python 3.9+
- After Effects (ExtendScript 실행 가능)

## 설치

```bash
git clone <저장소 URL>
cd 클로드

# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# 패키지 설치
pip install -r requirements.txt
```

## 빠른 시작

```bash
# 영상을 input/ 폴더에 넣은 뒤 한 줄로 실행
./run.sh input/영상.mp4
```

## 자동 색상 감지

별도 설정 없이 실행하면 도구가 영상에서 객체 색상을 자동으로 찾아낸다.

```bash
# 자동 감지 (기본 동작)
./run.sh input/video.mp4

# 색상 수동 지정 (파랑 객체)
./run.sh input/video.mp4 --color blue

# 자동 감지 끄기 (기본값: 빨강으로 추출)
./run.sh input/video.mp4 --no-auto
```

지원 색상: `red` `orange` `yellow` `green` `cyan` `blue` `purple` `pink`

신뢰도(confidence)가 0.5 미만이면 경고를 출력한다. 이 경우 `--color` 옵션으로 직접 지정하면 더 정확하다.

`output/` 폴더에 결과물이 생성된다:
- `<이름>_coords.json` — 프레임별 좌표 데이터
- `<이름>_debug.mp4` — 추적 결과 시각화 영상
- `<이름>.jsx` — After Effects 실행 스크립트

## 단계별 실행

```bash
# 1. 좌표 추출
venv/bin/python src/extract_coords.py input/video.mp4

# 2. AE 스크립트 변환
venv/bin/python src/json_to_jsx.py output/video_coords.json
```

## After Effects 적용

1. 1280×720, 30fps 컴포지션 열기
2. `File → Scripts → Run Script File → <이름>.jsx` 선택
3. null object에 키프레임 자동 적용 완료

## 보안 안내

`input/`과 `output/`은 `.gitignore`로 제외되어 있습니다.
클라이언트 영상과 추출 결과물은 로컬에서만 처리되며 저장소에 올라가지 않습니다.

## 폴더 구조

```
클로드/
├── input/                      # 입력 영상 (.mp4) — git 제외
├── output/                     # 결과물 (.json, .jsx, _debug.mp4) — git 제외
├── src/
│   ├── generate_test_video.py  # 테스트 영상 생성
│   ├── extract_coords.py       # 객체 좌표 추출
│   └── json_to_jsx.py          # AE 스크립트 변환
├── venv/                       # Python 가상환경 — git 제외
├── run.sh                      # 통합 실행 스크립트
├── requirements.txt
└── README.md
```
