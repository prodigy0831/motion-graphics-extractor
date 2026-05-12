"""
SAM 2 + OCR 기반 텍스트 객체 추적기

영상에서 텍스트 영역을 SAM 2로 추적하면서
색상·크기·굵기·내용 등 시각 메타데이터와 프레임별 opacity를 함께 추출한다.

사용법:
    venv_sam2/bin/python src/extract_text.py input/video.mp4 \
        --click-time 1.25 \
        --bbox 400,300,800,360
"""

import argparse
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
import torch

# ── Tesseract / Pillow 설치 확인 ────────────────────────────────
try:
    import pytesseract
    from PIL import Image as PILImage
    _TESSERACT_PKG = True
except ImportError:
    _TESSERACT_PKG = False

BASE_DIR   = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "sam2_base_plus.pt"
CONFIG     = "configs/sam2.1/sam2.1_hiera_b+.yaml"
OUTPUT_DIR = BASE_DIR / "output"

MIN_MASK_AREA  = 10      # 이 픽셀 수 미만 마스크는 미검출로 처리
MARKER_COLOR   = (255, 255, 255)  # 디버그 영상 마커 (흰색)
MARKER_SIZE    = 12


# ── 설치 확인 ──────────────────────────────────────────────────
def _check_dependencies():
    """pytesseract, Tesseract 바이너리 설치 여부를 확인한다."""
    if not _TESSERACT_PKG:
        print("오류: pytesseract 패키지가 설치되어 있지 않습니다.", flush=True)
        print("  설치: venv_sam2/bin/pip install pytesseract", flush=True)
        sys.exit(1)
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        print("오류: Tesseract OCR 엔진이 설치되어 있지 않습니다.", flush=True)
        print("  macOS 설치: brew install tesseract tesseract-lang", flush=True)
        print("  한국어 팩 확인: tesseract --list-langs | grep kor", flush=True)
        sys.exit(1)


# ── 프레임 추출 유틸 ───────────────────────────────────────────
def read_frame_at(video_path: Path, frame_idx: int) -> np.ndarray:
    """영상에서 특정 프레임을 BGR numpy 배열로 반환한다."""
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print(f"ERROR: 프레임 {frame_idx} 읽기 실패", flush=True)
        sys.exit(1)
    return frame


def extract_frames_to_dir(video_path: Path, out_dir: Path, total: int) -> int:
    """영상 전체 프레임을 JPEG로 저장한다 (SAM 2 video predictor 입력용)."""
    cap   = cv2.VideoCapture(str(video_path))
    count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        cv2.imwrite(str(out_dir / f"{count:06d}.jpg"), frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        count += 1
    cap.release()
    return count


# ── 마스크 분석 함수 ───────────────────────────────────────────
def mask_to_bbox(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """bool 마스크에서 (x1, y1, x2, y2) bounding box를 반환한다."""
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def mask_to_centroid(mask: np.ndarray) -> Optional[Tuple[int, int, int, int, int]]:
    """bool 마스크에서 (cx, cy, w, h, area) 또는 None을 반환한다."""
    bbox = mask_to_bbox(mask)
    if bbox is None or mask.sum() < MIN_MASK_AREA:
        return None
    x1, y1, x2, y2 = bbox
    ys, xs = np.where(mask)
    cx = int(round(xs.mean()))
    cy = int(round(ys.mean()))
    return cx, cy, x2 - x1, y2 - y1, int(mask.sum())


def mask_to_angle(mask: np.ndarray) -> Optional[float]:
    """bool 마스크의 minAreaRect 각도를 [-90, 90) 범위로 반환한다."""
    pts = np.column_stack(np.where(mask)).astype(np.float32)
    if len(pts) < 5:
        return None
    # minAreaRect는 (col, row) 순서로 입력
    _, (w, h), angle = cv2.minAreaRect(pts[:, ::-1])
    if w < h:
        angle += 90.0
    return float(angle % 180 - 90)


def measure_contrast(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> float:
    """마스크 내부와 bbox 내 외부 픽셀의 밝기 차이를 계산한다 (opacity 추정 기준)."""
    H, W = frame_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W - 1, x2), min(H - 1, y2)

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(float)

    inside = gray[mask]
    bbox_region = np.zeros_like(mask)
    bbox_region[y1:y2 + 1, x1:x2 + 1] = True
    outside = gray[bbox_region & ~mask]

    if len(inside) == 0:
        return 0.0
    mean_in  = inside.mean()
    mean_out = outside.mean() if len(outside) > 0 else mean_in
    return float(abs(mean_in - mean_out))


# ── 텍스트 메타데이터 추출 함수 ───────────────────────────────
def extract_text_color(frame_bgr: np.ndarray, mask: np.ndarray) -> str:
    """마스크 내 픽셀 평균 색상을 #RRGGBB 형태로 반환한다."""
    pixels = frame_bgr[mask]  # (N, 3) BGR
    if len(pixels) == 0:
        return "#000000"
    mean_bgr = pixels.mean(axis=0)
    r, g, b  = int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])
    return f"#{r:02X}{g:02X}{b:02X}"


def classify_weight(mask: np.ndarray) -> str:
    """마스크 채움 비율로 텍스트 굵기를 분류한다.

    채움 비율 = 마스크 픽셀 수 / bounding box 면적
    0.50 이상 → Bold, 0.30~0.50 → Regular, 미만 → Light
    """
    bbox = mask_to_bbox(mask)
    if bbox is None:
        return "Regular"
    x1, y1, x2, y2 = bbox
    bbox_area = (x2 - x1 + 1) * (y2 - y1 + 1)
    if bbox_area == 0:
        return "Regular"
    fill = mask.sum() / bbox_area
    if fill >= 0.50:
        return "Bold"
    elif fill >= 0.30:
        return "Regular"
    return "Light"


def ocr_text_content(frame_bgr: np.ndarray, mask: np.ndarray) -> str:
    """마스크 영역을 크롭해 Tesseract OCR로 텍스트를 인식한다."""
    bbox = mask_to_bbox(mask)
    if bbox is None:
        return ""

    H, W = frame_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    # 주변 여백 추가 (OCR 정확도 향상)
    pad = 8
    x1 = max(0, x1 - pad);  y1 = max(0, y1 - pad)
    x2 = min(W - 1, x2 + pad); y2 = min(H - 1, y2 + pad)

    crop = frame_bgr[y1:y2 + 1, x1:x2 + 1]

    # 최소 50px 높이로 확대 (소형 텍스트 인식 향상)
    h_crop = crop.shape[0]
    scale  = max(1.0, 50.0 / h_crop)
    if scale > 1.0:
        new_w = int(crop.shape[1] * scale)
        new_h = int(crop.shape[0] * scale)
        crop  = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    pil_img  = PILImage.fromarray(crop_rgb)

    # PSM 7: 단일 텍스트 라인 모드
    try:
        text = pytesseract.image_to_string(
            pil_img, lang="kor+eng", config="--psm 7"
        ).strip()
    except pytesseract.TesseractError:
        # 한국어 팩 없을 때 영어로 폴백
        text = pytesseract.image_to_string(
            pil_img, lang="eng", config="--psm 7"
        ).strip()
    return text


# ── 기준 프레임 메타데이터 ─────────────────────────────────────
def build_baseline_metadata(
    frame_bgr: np.ndarray,
    mask: np.ndarray,
    bbox: Tuple[int, int, int, int],
) -> dict:
    """기준 프레임에서 텍스트 시각 메타데이터를 추출한다."""
    comp = mask_to_centroid(mask)
    size_px = comp[3] if comp else 0  # bounding box 높이

    return {
        "content":            ocr_text_content(frame_bgr, mask),
        "color":              extract_text_color(frame_bgr, mask),
        "size_px":            size_px,
        "weight":             classify_weight(mask),
        "category":           "Sans-serif",
        "baseline_contrast":  round(measure_contrast(frame_bgr, mask, bbox), 4),
    }


# ── 메인 추출 함수 ────────────────────────────────────────────
def run(
    video_path: Path,
    click_time: float,
    bbox: Tuple[int, int, int, int],
) -> None:
    """텍스트 객체를 양방향 추적하고 JSON + 디버그 영상을 저장한다."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    stem       = video_path.stem
    json_path    = OUTPUT_DIR / f"{stem}_text_coords.json"
    debug_path   = OUTPUT_DIR / f"{stem}_text_debug.mp4"
    masked_path  = OUTPUT_DIR / f"{stem}_text_masked.png"

    # ── 1. 영상 기본 정보 ─────────────────────────────────────
    cap = cv2.VideoCapture(str(video_path))
    W   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    N   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    click_frame = int(round(click_time * fps))
    click_frame = max(0, min(N - 1, click_frame))

    print(f"영상: {video_path.name}  {W}x{H}  {fps:.1f}fps  {N}f", flush=True)
    print(f"클릭: time={click_time}s  frame={click_frame}  bbox={bbox}", flush=True)

    # ── 2. 기준 프레임 추출 ───────────────────────────────────
    baseline_bgr = read_frame_at(video_path, click_frame)
    baseline_rgb = cv2.cvtColor(baseline_bgr, cv2.COLOR_BGR2RGB)

    # ── 3. SAM 2 image predictor → 기준 마스크 ───────────────
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"디바이스: {device}", flush=True)
    print("SAM 2 image predictor 로드 중...", flush=True)

    from sam2.build_sam import build_sam2, build_sam2_video_predictor
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    img_model = build_sam2(CONFIG, str(MODEL_PATH), device=device)
    img_pred  = SAM2ImagePredictor(img_model)

    x1, y1, x2, y2 = bbox
    box_arr = np.array([x1, y1, x2, y2], dtype=np.float32)

    with torch.inference_mode():
        img_pred.set_image(baseline_rgb)
        masks, scores, _ = img_pred.predict(
            box=box_arr,
            multimask_output=True,
        )

    best_idx      = int(np.argmax(scores))
    baseline_mask = masks[best_idx].astype(bool)  # (H, W)

    if baseline_mask.sum() < MIN_MASK_AREA:
        print("ERROR: 기준 프레임에서 텍스트 마스크를 찾지 못했습니다.", flush=True)
        print("  bbox 좌표와 click_time을 확인해 주세요.", flush=True)
        sys.exit(1)

    print(f"기준 마스크: {int(baseline_mask.sum())}px  (신뢰도: {scores[best_idx]:.3f})", flush=True)

    # ── 3-b. 마스크 영역 크롭 이미지 저장 (AI 참조용) ────────────
    ys_m, xs_m = np.where(baseline_mask)
    if len(ys_m) > 0:
        pad  = 20
        x1m  = max(0, int(xs_m.min()) - pad)
        y1m  = max(0, int(ys_m.min()) - pad)
        x2m  = min(W - 1, int(xs_m.max()) + pad)
        y2m  = min(H - 1, int(ys_m.max()) + pad)
        cv2.imwrite(str(masked_path), baseline_bgr[y1m:y2m + 1, x1m:x2m + 1])

    # ── 4. 기준 프레임 텍스트 메타데이터 ──────────────────────
    print("텍스트 메타데이터 추출 중...", flush=True)
    text_meta    = build_baseline_metadata(baseline_bgr, baseline_mask, bbox)
    baseline_con = text_meta["baseline_contrast"]
    baseline_comp = mask_to_centroid(baseline_mask)
    baseline_area = baseline_comp[4] if baseline_comp else 1
    baseline_size = math.sqrt(baseline_area / math.pi) * 2.0

    print(f"  내용: '{text_meta['content']}'  색상: {text_meta['color']}  "
          f"크기: {text_meta['size_px']}px  굵기: {text_meta['weight']}", flush=True)

    # ── 5. 프레임 추출 (video predictor용) ───────────────────
    print("프레임 추출 중...", flush=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="sam2_text_"))

    raw_comp    = [None] * N  # (cx,cy,w,h,area) or None
    raw_angle   = [None] * N  # float or None
    raw_masks   = [None] * N  # bool (H,W) or None
    raw_contrast = [0.0]  * N  # float

    try:
        extract_frames_to_dir(video_path, temp_dir, N)

        # ── 6. SAM 2 video predictor → 양방향 추적 ───────────
        print("SAM 2 video predictor 로드 중...", flush=True)
        vid_pred = build_sam2_video_predictor(CONFIG, str(MODEL_PATH), device=device)

        def process_mask(frame_idx: int, masks) -> None:
            if masks is None or len(masks) == 0:
                return
            mb   = (masks[0][0].cpu().numpy() > 0.5).astype(bool)
            comp = mask_to_centroid(mb)
            if comp is None:
                return
            raw_comp[frame_idx]    = comp
            raw_angle[frame_idx]   = mask_to_angle(mb)
            raw_masks[frame_idx]   = mb

            # 현재 프레임 BGR 읽기 (contrast 계산용)
            cap_tmp = cv2.VideoCapture(str(video_path))
            cap_tmp.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, fr = cap_tmp.read()
            cap_tmp.release()
            if ret:
                raw_contrast[frame_idx] = measure_contrast(fr, mb, bbox)

        print("SAM 2 추적 시작...", flush=True)
        done = set()

        with torch.inference_mode():
            state = vid_pred.init_state(video_path=str(temp_dir))
            vid_pred.add_new_points_or_box(
                inference_state=state,
                frame_idx=click_frame,
                obj_id=1,
                box=box_arr,
            )

            # 순방향 (click_frame → 끝)
            for fi, oids, masks in vid_pred.propagate_in_video(
                    state, start_frame_idx=click_frame):
                process_mask(fi, masks)
                done.add(fi)
                if len(done) % 10 == 0 or len(done) == N:
                    print(f"PROGRESS: {len(done)} / {N}", flush=True)

            # 역방향 (click_frame-1 → 처음)
            if click_frame > 0:
                for fi, oids, masks in vid_pred.propagate_in_video(
                        state, start_frame_idx=click_frame, reverse=True):
                    process_mask(fi, masks)
                    done.add(fi)
                    if len(done) % 10 == 0 or len(done) == N:
                        print(f"PROGRESS: {len(done)} / {N}", flush=True)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # ── 7. 프레임별 데이터 조합 ───────────────────────────────
    frames_data = []
    for i in range(N):
        comp  = raw_comp[i]
        angle = raw_angle[i]

        if comp is None:
            frames_data.append({
                "frame": i, "x": None, "y": None,
                "scale": None, "rotation": None, "opacity": 0.0,
            })
        else:
            cx, cy, bw, bh, area = comp
            cur_size = math.sqrt(area / math.pi) * 2.0
            scale    = round(cur_size / baseline_size, 4) if baseline_size > 0 else 1.0

            # opacity: 현재 contrast / baseline contrast
            if baseline_con > 0:
                opacity = min(1.0, max(0.0, raw_contrast[i] / baseline_con))
            else:
                opacity = 1.0

            frames_data.append({
                "frame":    i,
                "x":        cx,
                "y":        cy,
                "scale":    round(scale, 4),
                "rotation": round(angle, 2) if angle is not None else 0.0,
                "opacity":  round(opacity, 4),
            })

    # ── 8. JSON 저장 ──────────────────────────────────────────
    import json
    payload = {
        "object_type": "text",
        "video_info": {
            "fps":          fps,
            "width":        W,
            "height":       H,
            "total_frames": N,
        },
        "click_info": {
            "click_time":  click_time,
            "click_frame": click_frame,
            "bbox":        list(bbox),
        },
        "text_metadata": text_meta,
        "frames":        frames_data,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ── 9. 디버그 영상 저장 ───────────────────────────────────
    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (W, H))
    if not writer.isOpened():
        fourcc = cv2.VideoWriter_fourcc(*"H264")
        writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (W, H))

    cap = cv2.VideoCapture(str(video_path))
    for i, fd in enumerate(frames_data):
        ret, frame = cap.read()
        if not ret:
            break

        if fd["x"] is not None:
            mb = raw_masks[i]
            if mb is not None and mb.any():
                overlay = frame.copy()
                overlay[mb] = (0, 0, 255)
                cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

            # 중심점 십자 마커
            cx, cy = fd["x"], fd["y"]
            cv2.line(frame, (cx - MARKER_SIZE, cy), (cx + MARKER_SIZE, cy),
                     MARKER_COLOR, 2, cv2.LINE_AA)
            cv2.line(frame, (cx, cy - MARKER_SIZE), (cx, cy + MARKER_SIZE),
                     MARKER_COLOR, 2, cv2.LINE_AA)

            # opacity 텍스트
            label = f"{text_meta['content']}  opacity={fd['opacity']:.2f}"
            cv2.putText(frame, label, (cx + 14, cy - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            cv2.putText(frame, "NOT VISIBLE  opacity=0.00", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1, cv2.LINE_AA)

        # 클릭 시점 라벨
        if i == click_frame:
            cv2.putText(frame, "CLICK FRAME (baseline)", (20, H - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 235, 255), 2, cv2.LINE_AA)

        writer.write(frame)
    cap.release()
    writer.release()

    # ── 10. 완료 보고 ─────────────────────────────────────────
    visible = sum(1 for f in frames_data if f["x"] is not None)
    print(f"DONE: {json_path}", flush=True)
    print(f"  추적 프레임: {visible}/{N}  |  디버그: {debug_path.name}", flush=True)

    # ── 11. .jsx 자동 생성 ────────────────────────────────────────
    import subprocess
    venv_py    = BASE_DIR / "venv_sam2" / "bin" / "python"
    jsx_script = BASE_DIR / "src" / "text_json_to_jsx.py"
    subprocess.run([str(venv_py), str(jsx_script), str(json_path)], check=False)


# ── 진입점 ───────────────────────────────────────────────────
if __name__ == "__main__":
    _check_dependencies()

    parser = argparse.ArgumentParser(description="SAM 2 + OCR 텍스트 객체 추적기")
    parser.add_argument("video",         help="입력 영상 파일 경로")
    parser.add_argument("--click-time",  type=float, required=True,
                        help="텍스트가 가장 명확한 시점 (초)")
    parser.add_argument("--bbox",        required=True,
                        help="텍스트 영역 박스: x1,y1,x2,y2  (픽셀, 클릭 시점 기준)")
    args = parser.parse_args()

    try:
        coords = [int(v) for v in args.bbox.split(",")]
        if len(coords) != 4:
            raise ValueError
        bbox = tuple(coords)
    except ValueError:
        print("오류: --bbox 형식은 x1,y1,x2,y2 (쉼표 구분 정수) 입니다.", flush=True)
        sys.exit(1)

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"오류: 영상 파일을 찾을 수 없습니다 → {video_path}", flush=True)
        sys.exit(1)

    try:
        run(video_path, args.click_time, bbox)
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
