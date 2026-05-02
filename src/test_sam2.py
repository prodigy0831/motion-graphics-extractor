"""
SAM 2 단독 작동 확인 스크립트

input/test_ball.mp4의 첫 프레임에서 클릭 포인트로 객체 마스크를 생성하고
output/sam2_test_mask.png 로 저장한다.

사용법:
    venv_sam2/bin/python src/test_sam2.py
"""

import time
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

BASE_DIR = Path(__file__).parent.parent

# SAM 2 경로를 sys.path에 추가 (editable install이 되어 있으므로 불필요하지만 명시)
SAM2_DIR = BASE_DIR / "external" / "sam2"
MODEL_PATH = BASE_DIR / "models" / "sam2_base_plus.pt"
CONFIG_NAME = "configs/sam2.1/sam2.1_hiera_b+.yaml"

INPUT_VIDEO = BASE_DIR / "input" / "test_ball.mp4"
OUTPUT_MASK = BASE_DIR / "output" / "sam2_test_mask.png"

# frame 74에서 공이 (636, 358) 근처에 위치 — 화면 중앙과 일치
CLICK_POINT = [640, 360]
TARGET_FRAME = 74  # 공이 화면 중앙에 있는 프레임


def main() -> None:
    """SAM 2 단독 작동 확인."""
    # ── 디바이스 선택 ──────────────────────────────────────────────
    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")
    print(f"사용 디바이스: {device}")

    # ── SAM 2 모델 로드 ────────────────────────────────────────────
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    print("SAM 2 모델 로드 중...")
    t0 = time.time()
    sam2_model = build_sam2(CONFIG_NAME, str(MODEL_PATH), device=device)
    predictor = SAM2ImagePredictor(sam2_model)
    print(f"  모델 로드 완료: {time.time() - t0:.2f}초")

    # ── 대상 프레임 추출 (공이 화면 중앙에 있는 프레임) ───────────
    cap = cv2.VideoCapture(str(INPUT_VIDEO))
    cap.set(cv2.CAP_PROP_POS_FRAMES, TARGET_FRAME)
    ret, frame_bgr = cap.read()
    cap.release()
    print(f"대상 프레임: {TARGET_FRAME}")
    if not ret:
        print(f"오류: 영상을 읽을 수 없습니다 → {INPUT_VIDEO}")
        sys.exit(1)
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w = frame_rgb.shape[:2]
    print(f"프레임 크기: {w}x{h}")

    # ── 마스크 생성 ────────────────────────────────────────────────
    predictor.set_image(frame_rgb)

    point = np.array([CLICK_POINT], dtype=np.float32)
    label = np.array([1], dtype=np.int32)  # 1 = foreground

    print(f"추론 시작 (클릭 포인트: {CLICK_POINT})...")
    t1 = time.time()
    masks, scores, _ = predictor.predict(
        point_coords=point,
        point_labels=label,
        multimask_output=True,
    )
    elapsed = time.time() - t1
    print(f"  추론 완료: {elapsed:.3f}초")

    # 신뢰도가 가장 높은 마스크 선택
    best_idx = int(np.argmax(scores))
    best_mask = masks[best_idx].astype(bool)  # (H, W) bool — SAM 2 출력이 float일 수 있음

    pixel_count = int(best_mask.sum())
    print(f"  선택된 마스크 신뢰도: {scores[best_idx]:.4f}")
    print(f"  마스크 픽셀 수: {pixel_count:,}px")

    # ── 결과 시각화·저장 ──────────────────────────────────────────
    OUTPUT_MASK.parent.mkdir(exist_ok=True)
    overlay = frame_bgr.copy()
    # 마스크 영역을 반투명 초록으로 강조
    overlay[best_mask] = overlay[best_mask] * 0.5 + np.array([0, 180, 0]) * 0.5
    # 클릭 포인트에 빨간 원 표시
    cv2.circle(overlay, tuple(CLICK_POINT), 8, (0, 0, 255), -1)

    cv2.imwrite(str(OUTPUT_MASK), overlay)
    print(f"\n결과 저장: {OUTPUT_MASK}")

    # ── 요약 ──────────────────────────────────────────────────────
    print("\n=== 검증 요약 ===")
    print(f"  디바이스:    {device}")
    print(f"  추론 시간:   {elapsed:.3f}초 {'✅' if elapsed < 1.0 else '⚠️  1초 초과'}")
    print(f"  마스크 픽셀: {pixel_count:,}px")


if __name__ == "__main__":
    main()
