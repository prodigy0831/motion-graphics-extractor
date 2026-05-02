"""
SAM 2 기반 객체 좌표 추출기

클릭 포인트를 SAM 2에 전달해 영상 전체를 추적하고
extract_coords.py와 동일한 JSON 구조로 저장한다.

사용법:
    venv_sam2/bin/python src/extract_with_sam2.py \
        --video input/kling_test.mp4 \
        --click-frame 0 \
        --click-x 640 \
        --click-y 252
"""

import argparse
import cv2
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch

BASE_DIR   = Path(__file__).parent.parent
MODEL_PATH = BASE_DIR / "models" / "sam2_base_plus.pt"
CONFIG     = "configs/sam2.1/sam2.1_hiera_b+.yaml"
OUTPUT_DIR = BASE_DIR / "output"

# extract_coords.py와 동일한 상수
MIN_AREA    = 20
SMOOTH_WIN  = 5
CIRCLE_MIN  = 0.85
CIRCLE_MAX  = 1.15
ROT_WRAP    = 90.0
AREA_RATIO  = 0.5
MARKER_COLOR = (0, 255, 0)
MARKER_SIZE  = 20


# ── 유틸리티 (extract_coords.py와 동일 로직) ──────────────────

def mask_to_component(mask_bool: np.ndarray):
    """bool 마스크에서 가장 큰 connected component (cx,cy,w,h,area) 반환."""
    m = mask_bool.astype(np.uint8) * 255
    n, _, stats, centroids = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return None
    best = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    if stats[best, cv2.CC_STAT_AREA] < MIN_AREA:
        return None
    return (
        int(round(centroids[best][0])),
        int(round(centroids[best][1])),
        int(stats[best, cv2.CC_STAT_WIDTH]),
        int(stats[best, cv2.CC_STAT_HEIGHT]),
        int(stats[best, cv2.CC_STAT_AREA]),
    )


def mask_to_rotation(mask_bool: np.ndarray):
    """bool 마스크에서 minAreaRect 각도와 원형 여부 (angle, is_circular) 반환."""
    m = mask_bool.astype(np.uint8) * 255
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < MIN_AREA:
        return None
    (_, _), (w, h), angle = cv2.minAreaRect(largest)
    if w < h:
        w, h = h, w
        angle += 90.0
    asp = w / h if h > 0 else 1.0
    return angle, (CIRCLE_MIN <= asp <= CIRCLE_MAX)


def smooth_values(values, window=SMOOTH_WIN):
    result = []
    half = window // 2
    for i, val in enumerate(values):
        if val is None:
            result.append(None)
            continue
        start = max(0, i - half)
        end   = min(len(values), i + half + 1)
        nbrs  = [values[j] for j in range(start, end) if values[j] is not None]
        result.append(sum(nbrs) / len(nbrs))
    return result


def calc_scales(smoothed, baseline=None):
    base = baseline if baseline is not None else next((w for w in smoothed if w), None)
    if not base:
        return [None] * len(smoothed)
    return [round((w / base) * 100.0, 1) if w is not None else None for w in smoothed]


def accumulate_rotations_from_ref(raw_angles, ref_idx):
    n = len(raw_angles)
    result = [None] * n
    ref = raw_angles[ref_idx]
    if ref is None:
        return result
    result[ref_idx] = 0.0
    acc, prev = 0.0, ref
    for i in range(ref_idx + 1, n):
        a = raw_angles[i]
        if a is None:
            continue
        diff = a - prev
        if diff > ROT_WRAP:   diff -= 180.0
        elif diff < -ROT_WRAP: diff += 180.0
        acc += diff; prev = a
        result[i] = round(acc, 1)
    acc, prev = 0.0, ref
    for i in range(ref_idx - 1, -1, -1):
        a = raw_angles[i]
        if a is None:
            continue
        df = prev - a
        if df > ROT_WRAP:   df -= 180.0
        elif df < -ROT_WRAP: df += 180.0
        acc -= df; prev = a
        result[i] = round(acc, 1)
    return result


# ── 프레임 추출 ───────────────────────────────────────────────

def extract_frames(video_path: Path, temp_dir: Path, total: int) -> int:
    """영상을 JPEG 프레임으로 추출해 temp_dir에 저장한다."""
    cap = cv2.VideoCapture(str(video_path))
    count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        cv2.imwrite(str(temp_dir / f"{count:06d}.jpg"), frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        count += 1
    cap.release()
    return count


# ── 메인 추출 함수 ────────────────────────────────────────────

def run(video_path: Path, click_frame: int, click_x: int, click_y: int):
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem      = video_path.stem
    json_path = OUTPUT_DIR / f"{stem}_coords.json"
    debug_path = OUTPUT_DIR / f"{stem}_debug.mp4"

    cap  = cv2.VideoCapture(str(video_path))
    W    = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps  = cap.get(cv2.CAP_PROP_FPS)
    N    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    print(f"영상: {video_path.name}  {W}x{H}  {fps:.1f}fps  {N}f", flush=True)
    print(f"클릭: frame={click_frame}  ({click_x}, {click_y})", flush=True)

    # 디바이스 선택
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"디바이스: {device}", flush=True)

    # SAM 2 로드
    print("SAM 2 로드 중...", flush=True)
    from sam2.build_sam import build_sam2_video_predictor
    predictor = build_sam2_video_predictor(CONFIG, str(MODEL_PATH), device=device)

    # 프레임 추출
    print("프레임 추출 중...", flush=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="sam2_"))
    try:
        extract_frames(video_path, temp_dir, N)

        raw_comp = [None] * N   # (cx,cy,w,h,area) or None
        raw_rot  = [None] * N   # (angle, is_circular) or None

        def process_mask(frame_idx, masks):
            # masks는 텐서 또는 리스트일 수 있으므로 len() 체크
            if masks is None or len(masks) == 0:
                return
            mb = (masks[0][0].cpu().numpy() > 0.5)
            comp = mask_to_component(mb)
            rot  = mask_to_rotation(mb) if comp else None
            raw_comp[frame_idx] = comp
            raw_rot[frame_idx]  = rot

        print("SAM 2 추적 시작...", flush=True)
        done = set()
        with torch.inference_mode():
            state = predictor.init_state(video_path=str(temp_dir))
            predictor.add_new_points_or_box(
                inference_state=state,
                frame_idx=click_frame,
                obj_id=1,
                points=np.array([[click_x, click_y]], dtype=np.float32),
                labels=np.array([1], dtype=np.int32),
            )
            # 순방향 (click_frame → 끝)
            for fi, oids, masks in predictor.propagate_in_video(
                    state, start_frame_idx=click_frame):
                process_mask(fi, masks)
                done.add(fi)
                if len(done) % 10 == 0 or len(done) == N:
                    print(f"PROGRESS: {len(done)} / {N}", flush=True)

            # 역방향 (click_frame-1 → 처음, 해당 구간 있을 때만)
            if click_frame > 0:
                for fi, oids, masks in predictor.propagate_in_video(
                        state, start_frame_idx=click_frame, reverse=True):
                    process_mask(fi, masks)
                    done.add(fi)
                    if len(done) % 10 == 0 or len(done) == N:
                        print(f"PROGRESS: {len(done)} / {N}", flush=True)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # ── 후처리 (extract_coords.py와 동일) ──────────────────────
    ref_area = raw_comp[click_frame][4] if raw_comp[click_frame] else None
    ref_size = math.sqrt(ref_area / math.pi) * 2.0 if ref_area else None

    raw_sizes    = [math.sqrt(r[4] / math.pi) * 2.0 if r else None for r in raw_comp]
    smoothed     = smooth_values(raw_sizes)
    scales       = calc_scales(smoothed, baseline=ref_size)

    votes       = [r[1] for r in raw_rot if r is not None]
    is_circular = (sum(votes) / len(votes)) >= 0.5 if votes else True

    if is_circular:
        rotations = [0.0 if r else None for r in raw_rot]
    else:
        filtered = []
        for comp, rot in zip(raw_comp, raw_rot):
            if comp and rot and ref_area and (comp[4] / ref_area < AREA_RATIO):
                rot = None
            filtered.append(rot)
        raw_angles = [r[0] if r else None for r in filtered]
        rotations  = accumulate_rotations_from_ref(raw_angles, click_frame)

    # ── frames_data 조합 ───────────────────────────────────────
    frames_data = []
    for i, (comp, scale, rotation) in enumerate(zip(raw_comp, scales, rotations)):
        if comp is None:
            frames_data.append({
                "frame": i, "x": None, "y": None,
                "x_norm": None, "y_norm": None,
                "width": None, "height": None,
                "width_norm": None, "height_norm": None,
                "scale": None, "rotation": None,
            })
        else:
            cx, cy, w, h, _ = comp
            frames_data.append({
                "frame": i,
                "x": cx, "y": cy,
                "x_norm": round(cx / W, 4), "y_norm": round(cy / H, 4),
                "width": w, "height": h,
                "width_norm": round(w / W, 4), "height_norm": round(h / H, 4),
                "scale": scale, "rotation": rotation,
            })

    # ── JSON 저장 ──────────────────────────────────────────────
    payload = {
        "video": video_path.name,
        "width": W, "height": H, "fps": fps, "total_frames": N,
        "frames": frames_data,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ── debug 영상 저장 ────────────────────────────────────────
    # avc1(H.264) 코덱: Chromium/Electron에서 재생 가능
    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (W, H))
    if not writer.isOpened():
        fourcc = cv2.VideoWriter_fourcc(*"H264")
        writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (W, H))
    cap = cv2.VideoCapture(str(video_path))
    for fd in frames_data:
        ret, frame = cap.read()
        if not ret:
            break
        if fd["x"] is not None:
            x, y = fd["x"], fd["y"]
            cv2.line(frame, (x-MARKER_SIZE, y), (x+MARKER_SIZE, y),
                     MARKER_COLOR, 2, cv2.LINE_AA)
            cv2.line(frame, (x, y-MARKER_SIZE), (x, y+MARKER_SIZE),
                     MARKER_COLOR, 2, cv2.LINE_AA)
        writer.write(frame)
    cap.release()
    writer.release()

    print(f"DONE: {json_path}", flush=True)

    # ── json_to_jsx 호출 ───────────────────────────────────────
    venv_py   = BASE_DIR / "venv" / "bin" / "python"
    jsx_script = BASE_DIR / "src" / "json_to_jsx.py"
    subprocess.run([str(venv_py), str(jsx_script), str(json_path)], check=False)


# ── 진입점 ───────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAM 2 기반 객체 좌표 추출기")
    parser.add_argument("--video",        required=True, help="입력 영상 경로")
    parser.add_argument("--click-frame",  type=int, required=True, help="클릭한 프레임 번호")
    parser.add_argument("--click-x",      type=int, required=True, help="영상 원본 x 좌표")
    parser.add_argument("--click-y",      type=int, required=True, help="영상 원본 y 좌표")
    args = parser.parse_args()

    try:
        run(Path(args.video), args.click_frame, args.click_x, args.click_y)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)
