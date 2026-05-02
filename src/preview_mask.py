"""SAM 2 image predictor로 단일 프레임 마스크 프리뷰 생성

사용법:
    venv_sam2/bin/python src/preview_mask.py \
        --video input/kling_test.mp4 \
        --click-time 0.542 \
        --click-x 648 \
        --click-y 147
"""

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

BASE_DIR   = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "sam2_base_plus.pt"
CONFIG     = "configs/sam2.1/sam2.1_hiera_b+.yaml"
OUTPUT_DIR = BASE_DIR / "output"


def run(video_path: Path, click_time: float, click_x: int, click_y: int):
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 해당 시점 프레임 추출
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_idx = int(round(click_time * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame_bgr = cap.read()
    cap.release()

    if not ret:
        print(f"ERROR: 프레임 {frame_idx} 읽기 실패", flush=True)
        sys.exit(1)

    H, W = frame_bgr.shape[:2]
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    # SAM 2 image predictor 로드
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    sam2_model = build_sam2(CONFIG, str(MODEL_PATH), device=device)
    predictor  = SAM2ImagePredictor(sam2_model)

    t0 = time.time()
    with torch.inference_mode():
        predictor.set_image(frame_rgb)
        masks, scores, _ = predictor.predict(
            point_coords=np.array([[click_x, click_y]], dtype=np.float32),
            point_labels=np.array([1], dtype=np.int32),
            multimask_output=True,
        )
    elapsed = time.time() - t0

    # 최고 점수 마스크 선택 (SAM 2 출력이 float일 수 있으므로 bool 변환)
    best  = int(np.argmax(scores))
    mask  = masks[best].astype(bool)  # (H, W) bool
    pixel_count = int(mask.sum())

    # BGRA PNG: #ef4444 (R=239,G=68,B=68) 50% 알파
    bgra = np.zeros((H, W, 4), dtype=np.uint8)
    bgra[mask, 0] = 68    # B
    bgra[mask, 1] = 68    # G
    bgra[mask, 2] = 239   # R
    bgra[mask, 3] = 128   # A (50%)

    ts       = int(time.time() * 1000)
    out_path = OUTPUT_DIR / f"preview_mask_{ts}.png"
    cv2.imwrite(str(out_path), bgra)

    print(f"MASK_READY: {out_path}", flush=True)
    print(f"pixels={pixel_count}  time={elapsed:.3f}s  frame={frame_idx}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAM 2 단일 프레임 마스크 프리뷰")
    parser.add_argument("--video",       required=True)
    parser.add_argument("--click-time",  type=float, required=True, help="클릭 시점 (초)")
    parser.add_argument("--click-x",     type=int,   required=True)
    parser.add_argument("--click-y",     type=int,   required=True)
    args = parser.parse_args()

    try:
        run(Path(args.video), args.click_time, args.click_x, args.click_y)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
