#!/usr/bin/env bash
# 모션그래픽 추출기 — 통합 실행 스크립트
# 영상 파일 한 개를 인자로 받아 좌표 추출 → .jsx 변환까지 일괄 처리한다.

set -euo pipefail   # 에러 즉시 중단, 미정의 변수 오류, 파이프 에러 감지

# ── 색상 정의 ──────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✅ $*${RESET}"; }
info() { echo -e "${CYAN}▶  $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $*${RESET}"; }
fail() { echo -e "${RED}❌ $*${RESET}"; exit 1; }

# ── 사용법 ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
    echo ""
    echo "사용법: ./run.sh input/[파일명].mp4"
    echo ""
    echo "예시:"
    echo "  ./run.sh input/test_ball.mp4"
    echo ""
    echo "동작 순서:"
    echo "  1. 빨간색 객체 좌표 추출  →  output/<이름>_coords.json"
    echo "  2. AE 키프레임 스크립트 생성  →  output/<이름>.jsx"
    echo ""
}

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

# ── 입력 파일 확인 ─────────────────────────────────────────────────
INPUT_FILE="$1"

if [[ ! -f "$INPUT_FILE" ]]; then
    fail "파일을 찾을 수 없습니다: $INPUT_FILE"
fi

# 파일 이름에서 확장자 없는 stem 추출 (예: input/test_ball.mp4 → test_ball)
BASENAME=$(basename "$INPUT_FILE")
STEM="${BASENAME%.*}"

JSON_PATH="${SCRIPT_DIR}/output/${STEM}_coords.json"
JSX_PATH="${SCRIPT_DIR}/output/${STEM}.jsx"

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${CYAN}  모션그래픽 추출기${RESET}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
info "입력 파일: $INPUT_FILE"
echo ""

# ── Step 1: venv 확인 및 활성화 ────────────────────────────────────
info "[1/3] 가상환경 확인..."
VENV_PYTHON="${SCRIPT_DIR}/venv/bin/python"
if [[ ! -f "$VENV_PYTHON" ]]; then
    fail "venv를 찾을 수 없습니다. 먼저 환경 설정을 완료해주세요:\n  python3 -m venv venv && venv/bin/pip install -r requirements.txt"
fi
ok "가상환경 준비 완료"
echo ""

# ── Step 2: 좌표 추출 ──────────────────────────────────────────────
info "[2/3] 객체 좌표 추출 시작..."
if ! "$VENV_PYTHON" "${SCRIPT_DIR}/src/extract_coords.py" "$INPUT_FILE"; then
    fail "좌표 추출 실패. 위 오류 메시지를 확인해주세요."
fi

# JSON 파일 생성 여부 검증
if [[ ! -f "$JSON_PATH" ]]; then
    fail "좌표 JSON이 생성되지 않았습니다: $JSON_PATH"
fi
ok "좌표 추출 완료 → $JSON_PATH"
echo ""

# ── Step 3: .jsx 변환 ──────────────────────────────────────────────
info "[3/3] After Effects 스크립트 생성 중..."
if ! "$VENV_PYTHON" "${SCRIPT_DIR}/src/json_to_jsx.py" "$JSON_PATH"; then
    fail ".jsx 변환 실패. 위 오류 메시지를 확인해주세요."
fi

if [[ ! -f "$JSX_PATH" ]]; then
    fail ".jsx 파일이 생성되지 않았습니다: $JSX_PATH"
fi
ok ".jsx 생성 완료 → $JSX_PATH"
echo ""

# ── 완료 ──────────────────────────────────────────────────────────
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}  파이프라인 완료!${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo "  📄 좌표 JSON  : $JSON_PATH"
echo "  🎬 AE 스크립트 : $JSX_PATH"
echo ""
echo "  After Effects 사용법:"
echo "  File → Scripts → Run Script File → $(basename "$JSX_PATH")"
echo ""
