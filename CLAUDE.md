# 모션그래픽 추출기 (Motion Graphics Extractor)

## 프로젝트 개요

- **이름**: 모션그래픽 추출기 (Motion Graphics Extractor)
- **목적**: AI(Kling 등)가 만든 모션그래픽 영상에서 객체의 움직임을 추출해 After Effects에서 재현 가능하게 만드는 도구
- **사용자**: 광고 영상 디자이너 (특히 AI 영상과 실사·모션그래픽을 결합하는 작업)
- **왜 필요한가**: AI는 새로 뽑을 때마다 다른 결과물을 내서 클라이언트의 디테일 수정 요청에 대응 못 함. 한 번 추출해서 AE로 가져오면 디자이너가 자유롭게 수정 가능.

## 완료된 작업 (P1 + P2 GUI/SAM 2)

### P1 — 색상 기반 파이프라인 (완료)
- end-to-end 파이프라인 구축: 영상 → JSON → .jsx
- P1-1: 객체 색상 자동 감지 (K-means, S-V 채널, 3개 영상 검증)
- P1-2: 객체 크기(scale) 변화 추출, AE Scale 키프레임 생성
- P1-3: 객체 회전(rotation) 추출, AE Rotation 키프레임 생성
  - 원형 객체 자동 감지 → 회전 생략
  - find_reference_frame: 면적 최대 프레임을 기준점으로
  - 알려진 한계: 2D 평면(Z축) 회전만 지원, 3D 회전은 P3
- 비례 좌표(x_norm, y_norm, width_norm, height_norm) JSON 필드 추가
- `run.sh` 통합 실행 스크립트

### P2 — SAM 2 + GUI (완료)
- SAM 2 환경 세팅: Python 3.11, PyTorch, MPS(Apple Silicon), sam2_base_plus 모델
- `src/extract_with_sam2.py`: SAM 2 video predictor 전체 영상 추적
- `src/preview_mask.py`: 클릭 직후 단일 프레임 image predictor로 0.4초 내 마스크 프리뷰
- debug 영상: 매 프레임 SAM 2 마스크를 빨강 반투명 오버레이 + 십자 마커
- GUI (Electron 32): 1~5단계 완성
  - 영상 드래그 → 객체 클릭 → 빨강 마스크 즉시 확인 → 추출 → 결과 검토 → .jsx 다운로드
  - 궤적/스케일/회전 그래프 시각화
- P1-4(다중 객체)는 SAM 2에서 자연스럽게 흡수 예정

### 수정된 버그
- fps 불일치: GUI fps=30 하드코딩 → 24fps 영상에서 클릭 프레임 어긋남
  → `--click-time` 인자 추가, Python이 실제 fps로 프레임 환산
- `masks[best]` boolean 인덱싱 에러: `.astype(bool)` 추가
- video.src에 .json 경로 박힘: `_coords.json → _debug.mp4` 변환 수정
- Electron 32 `file.path` deprecated: `webUtils.getPathForFile()` 전환

## 현재 단계

**P1 완료, P2 GUI + SAM 2 통합 완료.**

다음 작업:
- 베지어 곡선 단순화 (선형 키프레임 → 곡선 근사)
- 마스크 흔들림 노이즈 완화
- P3: 모션그래픽 데이터화 (자간/morphing/디졸브 곡선)

## 확장 로드맵

### P2 — 남은 작업
- 베지어 곡선 패스 출력 (선형 키프레임 대신 곡선 근사)
- 마스크 노이즈 완화 (흔들림 스무딩)

### P3 — 먼 가지치기 (매드업 입사 후 발전)
- 다중 객체 추적 (각각 다른 null object로)
- 모션그래픽 자체의 데이터화 (자간/morphing/디졸브 곡선까지)
- 플랫폼 독립적 출력 포맷 (AE 외 다른 툴 지원)
- 퍼포먼스 데이터와 결합한 모션 라이브러리
- 3D 회전 지원 (현재는 2D 평면 Z축만)

## 폴더 구조

```
클로드/
├── input/                      # 분석할 영상
├── output/                     # JSON, .jsx, _debug.mp4 결과물
├── src/
│   ├── generate_test_video.py  # 테스트 영상 생성 (avc1 코덱)
│   ├── extract_coords.py       # 색상 기반 좌표 추출 (P1)
│   ├── detect_color.py         # K-means 자동 색상 감지
│   ├── json_to_jsx.py          # AE 스크립트 변환
│   ├── extract_with_sam2.py    # SAM 2 video predictor 추출 (P2)
│   └── preview_mask.py         # SAM 2 단일 프레임 마스크 프리뷰
├── gui/                        # Electron GUI
│   ├── main.js
│   ├── preload.js
│   ├── renderer.js
│   ├── index.html
│   └── style.css
├── venv/                       # Python 가상환경 (P1)
├── venv_sam2/                  # SAM 2 가상환경 (P2)
└── run.sh                      # 통합 실행 스크립트
```

## 코딩 규칙

- Python 3 사용
- 함수와 클래스에 한국어 docstring 작성
- 주요 변수명·함수명은 영어로, 주석은 한국어로
- type hint 사용
- 에러 발생 시 친절한 한국어 에러 메시지 출력 (사용자가 비개발자일 수 있음)
- 외부 API 사용 금지 (영상 보안)
- 모든 처리는 로컬에서 완결

## 작업 진행 방식

- 한 번에 한 단계씩만 진행
- 각 단계 끝나면 멈추고 다음 지시 기다림
- 큰 변경 전에는 반드시 사용자에게 의도 확인
- 작동 확인 안 된 코드를 다음 단계로 넘기지 말 것

## 주요 교훈

- end-to-end 동작 한 번 확인하는 게 기능 추가보다 우선
- GUI fps 하드코딩은 반드시 실제 영상 fps 기준으로 맞춰야 함
- SAM 2 image predictor는 video predictor보다 훨씬 빠름 (단일 프레임 0.4초)
- Electron CSP에서 `data:` URI는 blob URL로 우회하는 게 안전
