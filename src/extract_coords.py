"""
객체 좌표 추출 스크립트

영상에서 지정한 색상 객체의 중심 좌표를 프레임별로 추출해 JSON으로 저장한다.
색상을 지정하지 않으면 detect_color.py가 자동으로 감지한다.

사용법:
    python src/extract_coords.py input/video.mp4               # 자동 감지
    python src/extract_coords.py input/video.mp4 --color blue  # 수동 지정
    python src/extract_coords.py input/video.mp4 --no-auto     # 자동 감지 끄기 (기본 빨강)
"""

import cv2
import numpy as np
import json
import sys
import argparse
from pathlib import Path
from typing import Optional, Tuple, List, Dict


BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

# 디버그 영상 마커 설정
MARKER_COLOR = (0, 255, 0)  # BGR — 녹색
MARKER_SIZE = 20
MARKER_THICKNESS = 2

# 수동 지정용 색 이름 → HSV 범위 매핑 테이블
# 빨강(red)은 H 0-10과 170-180 두 구간을 사용하므로 detect_object_by_hsv에서 별도 처리
COLOR_HSV_MAP: Dict[str, Tuple[List[int], List[int]]] = {
    "red":    ([0,   120,  70], [10,  255, 255]),
    "orange": ([10,  120,  70], [22,  255, 255]),
    "yellow": ([22,  100, 100], [38,  255, 255]),
    "green":  ([38,   80,  70], [85,  255, 255]),
    "cyan":   ([85,   80,  70], [100, 255, 255]),
    "blue":   ([100,  80,  70], [130, 255, 255]),
    "purple": ([130,  80,  70], [155, 255, 255]),
    "pink":   ([155,  80,  70], [170, 255, 255]),
}

# 기본 색상 (--no-auto 옵션 시 사용)
DEFAULT_COLOR = "red"


def open_video(video_path: Path) -> cv2.VideoCapture:
    """영상 파일을 열고 VideoCapture 객체를 반환한다."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"오류: 영상 파일을 열 수 없습니다 → {video_path}")
        sys.exit(1)
    return cap


def get_video_info(cap: cv2.VideoCapture) -> dict:
    """영상의 기본 정보(해상도, fps, 총 프레임 수)를 반환한다."""
    return {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "total_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
    }


def detect_object_by_hsv(
    frame_bgr: np.ndarray,
    hsv_lower: np.ndarray,
    hsv_upper: np.ndarray,
    color_name: str = "",
) -> np.ndarray:
    """
    BGR 프레임에서 HSV 범위에 해당하는 픽셀을 찾아 이진 마스크를 반환한다.

    color_name이 "red"이면 H 170-180° 보조 범위를 자동으로 추가한다.
    빨강은 HSV에서 0°와 360° 양쪽에 걸쳐 있기 때문이다.
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, hsv_lower, hsv_upper)

    if color_name == "red":
        # 빨강 보조 범위: S·V는 주 범위와 동일하게 유지
        lower2 = np.array([170, hsv_lower[1], hsv_lower[2]])
        upper2 = np.array([180, hsv_upper[1], hsv_upper[2]])
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lower2, upper2))

    return mask


def calc_centroid(mask: np.ndarray) -> Optional[Tuple[int, int]]:
    """
    이진 마스크에서 객체의 중심점(centroid)을 계산한다.

    모멘트(moment)를 이용해 무게중심을 구한다.
    마스크가 비어있으면 None을 반환한다.
    """
    M = cv2.moments(mask)
    if M["m00"] == 0:
        return None
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return cx, cy


def draw_cross_marker(frame: np.ndarray, x: int, y: int) -> np.ndarray:
    """프레임 위에 녹색 십자(+) 마커를 그려 반환한다."""
    cv2.line(frame, (x - MARKER_SIZE, y), (x + MARKER_SIZE, y),
             MARKER_COLOR, MARKER_THICKNESS, cv2.LINE_AA)
    cv2.line(frame, (x, y - MARKER_SIZE), (x, y + MARKER_SIZE),
             MARKER_COLOR, MARKER_THICKNESS, cv2.LINE_AA)
    return frame


def save_coords_json(
    output_path: Path,
    video_name: str,
    info: dict,
    frames_data: List[dict],
) -> None:
    """추출한 좌표 데이터를 JSON 파일로 저장한다."""
    payload = {
        "video": video_name,
        "width": info["width"],
        "height": info["height"],
        "fps": info["fps"],
        "total_frames": info["total_frames"],
        "frames": frames_data,
    }
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def resolve_hsv(
    video_path: Path,
    color_arg: Optional[str],
    no_auto: bool,
) -> Tuple[np.ndarray, np.ndarray, str]:
    """
    색상 옵션에 따라 HSV 범위와 색 이름을 결정한다.

    우선순위:
        1. --color 수동 지정
        2. 자동 감지 (기본)
        3. --no-auto → 기본값(빨강) 사용
    """
    # ── 수동 지정 ──────────────────────────────────────────────────
    if color_arg:
        color_name = color_arg.lower()
        if color_name not in COLOR_HSV_MAP:
            print(f"오류: 알 수 없는 색상 이름 '{color_arg}'")
            print(f"  사용 가능: {', '.join(COLOR_HSV_MAP.keys())}")
            sys.exit(1)
        lo, hi = COLOR_HSV_MAP[color_name]
        print(f"🎨 수동 지정 색상: {color_name} (HSV {lo[0]}-{hi[0]}/{lo[1]}-{hi[1]}/{lo[2]}-{hi[2]})")
        return np.array(lo), np.array(hi), color_name

    # ── --no-auto: 기본값(빨강) ────────────────────────────────────
    if no_auto:
        lo, hi = COLOR_HSV_MAP[DEFAULT_COLOR]
        print(f"🎨 자동 감지 꺼짐. 기본 색상 사용: {DEFAULT_COLOR}")
        return np.array(lo), np.array(hi), DEFAULT_COLOR

    # ── 자동 감지 ──────────────────────────────────────────────────
    try:
        from detect_color import detect_object_color, COLOR_NAME_KO
    except ImportError:
        print("경고: detect_color 모듈을 불러올 수 없습니다. 기본 빨강으로 진행합니다.")
        lo, hi = COLOR_HSV_MAP[DEFAULT_COLOR]
        return np.array(lo), np.array(hi), DEFAULT_COLOR

    result = detect_object_color(str(video_path))
    color_name = result["color_name"]
    color_ko   = result["color_name_ko"]
    confidence = result["confidence"]
    lo = result["hsv_lower"]
    hi = result["hsv_upper"]

    print(f"🎨 감지된 객체 색: {color_ko} (confidence {confidence:.2f})")
    if confidence < 0.5:
        print(f"⚠️  신뢰도가 낮습니다. --color 옵션으로 직접 지정 권장.")

    return np.array(lo), np.array(hi), color_name


def extract_coords(
    video_path: Path,
    hsv_lower: np.ndarray,
    hsv_upper: np.ndarray,
    color_name: str,
) -> None:
    """
    영상에서 지정 색상 객체의 좌표를 추출하고 JSON과 디버그 영상을 저장한다.
    """
    stem = video_path.stem
    json_path = OUTPUT_DIR / f"{stem}_coords.json"
    debug_path = OUTPUT_DIR / f"{stem}_debug.mp4"

    cap = open_video(video_path)
    info = get_video_info(cap)

    width = info["width"]
    height = info["height"]
    fps = info["fps"]
    total_frames = info["total_frames"]

    print(f"추출 시작: {video_path.name}")
    print(f"  해상도 {width}x{height}, {fps}fps, 총 {total_frames}프레임")

    OUTPUT_DIR.mkdir(exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (width, height))

    frames_data: List[dict] = []
    missing_count = 0

    for frame_idx in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            print(f"  경고: 프레임 {frame_idx}에서 영상이 끊겼습니다.")
            break

        if frame_idx % 50 == 0 or frame_idx == total_frames - 1:
            print(f"  프레임 {frame_idx + 1}/{total_frames} 처리 중...")

        mask = detect_object_by_hsv(frame, hsv_lower, hsv_upper, color_name)
        centroid = calc_centroid(mask)

        if centroid is None:
            print(f"  경고: 프레임 {frame_idx}에서 객체를 찾지 못했습니다. (x, y = null)")
            frames_data.append({"frame": frame_idx, "x": None, "y": None})
            missing_count += 1
        else:
            cx, cy = centroid
            frames_data.append({"frame": frame_idx, "x": cx, "y": cy})
            draw_cross_marker(frame, cx, cy)

        writer.write(frame)

    cap.release()
    writer.release()

    save_coords_json(json_path, video_path.name, info, frames_data)

    print(f"\n완료!")
    print(f"  좌표 JSON: {json_path}")
    print(f"  디버그 영상: {debug_path}")
    if missing_count > 0:
        print(f"  주의: {missing_count}개 프레임에서 객체를 찾지 못했습니다.")
    else:
        print(f"  전체 {len(frames_data)}프레임 좌표 추출 성공")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="영상에서 객체 좌표를 추출해 JSON과 AE용 디버그 영상을 생성합니다."
    )
    parser.add_argument("video", help="입력 영상 경로 (예: input/video.mp4)")
    parser.add_argument(
        "--color",
        metavar="COLOR",
        help=f"추적할 색상 직접 지정 (선택지: {', '.join(COLOR_HSV_MAP.keys())})",
    )
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="자동 색상 감지를 끄고 기본값(빨강)으로 추출합니다.",
    )
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다 → {video_path}")
        sys.exit(1)

    hsv_lower, hsv_upper, color_name = resolve_hsv(
        video_path, args.color, args.no_auto
    )
    extract_coords(video_path, hsv_lower, hsv_upper, color_name)
