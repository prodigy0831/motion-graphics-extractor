"""
객체 좌표 추출 스크립트

영상에서 빨간색 객체의 중심 좌표를 프레임별로 추출해 JSON으로 저장한다.
추적 결과를 시각적으로 확인할 수 있는 디버그 영상도 함께 생성한다.

사용법:
    python src/extract_coords.py input/test_ball.mp4
"""

import cv2
import numpy as np
import json
import sys
from pathlib import Path
from typing import Optional, Tuple


BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"

# HSV 빨간색 범위 (빨간색은 HSV에서 0°와 360° 근처 두 구간에 걸쳐 있음)
RED_LOWER_1 = np.array([0, 120, 70])
RED_UPPER_1 = np.array([10, 255, 255])
RED_LOWER_2 = np.array([170, 120, 70])
RED_UPPER_2 = np.array([180, 255, 255])

# 디버그 영상에 그릴 마커 색상 및 크기
MARKER_COLOR = (0, 255, 0)   # BGR — 녹색
MARKER_SIZE = 20
MARKER_THICKNESS = 2


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


def detect_red_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """
    BGR 프레임에서 빨간색 픽셀을 찾아 이진 마스크를 반환한다.

    빨간색은 HSV 색공간에서 0~10°와 170~180° 두 구간에 분포하므로
    두 범위를 OR로 합친다.
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, RED_LOWER_1, RED_UPPER_1)
    mask2 = cv2.inRange(hsv, RED_LOWER_2, RED_UPPER_2)
    return cv2.bitwise_or(mask1, mask2)


def calc_centroid(mask: np.ndarray) -> Optional[Tuple[int, int]]:
    """
    이진 마스크에서 객체의 중심점(centroid)을 계산한다.

    모멘트(moment)를 이용해 무게중심을 구한다.
    마스크가 비어있으면 None을 반환한다.
    """
    M = cv2.moments(mask)
    if M["m00"] == 0:
        return None  # 빨간 픽셀 없음
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return cx, cy


def draw_cross_marker(
    frame: np.ndarray, x: int, y: int
) -> np.ndarray:
    """프레임 위에 녹색 십자(+) 마커를 그려 반환한다."""
    # 가로선
    cv2.line(frame, (x - MARKER_SIZE, y), (x + MARKER_SIZE, y),
             MARKER_COLOR, MARKER_THICKNESS, cv2.LINE_AA)
    # 세로선
    cv2.line(frame, (x, y - MARKER_SIZE), (x, y + MARKER_SIZE),
             MARKER_COLOR, MARKER_THICKNESS, cv2.LINE_AA)
    return frame


def save_coords_json(
    output_path: Path,
    video_name: str,
    info: dict,
    frames_data: list[dict],
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


def extract_coords(video_path: Path) -> None:
    """
    영상에서 빨간색 객체의 좌표를 추출하고 JSON과 디버그 영상을 저장한다.
    """
    stem = video_path.stem  # 확장자 제외한 파일명
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

    # 디버그 영상 작성기 초기화
    OUTPUT_DIR.mkdir(exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (width, height))

    frames_data: list[dict] = []
    missing_count = 0

    for frame_idx in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            # 영상이 예상보다 짧게 끝난 경우
            print(f"  경고: 프레임 {frame_idx}에서 영상이 끊겼습니다.")
            break

        # 진행 상황 출력 (50프레임마다)
        if frame_idx % 50 == 0 or frame_idx == total_frames - 1:
            print(f"  프레임 {frame_idx + 1}/{total_frames} 처리 중...")

        mask = detect_red_mask(frame)
        centroid = calc_centroid(mask)

        if centroid is None:
            # 이 프레임에서 빨간 객체를 찾지 못함
            print(f"  경고: 프레임 {frame_idx}에서 객체를 찾지 못했습니다. (x, y = null)")
            frames_data.append({"frame": frame_idx, "x": None, "y": None})
            missing_count += 1
        else:
            cx, cy = centroid
            frames_data.append({"frame": frame_idx, "x": cx, "y": cy})
            # 디버그 영상에 마커 추가
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
    if len(sys.argv) < 2:
        print("사용법: python src/extract_coords.py <영상 경로>")
        print("  예시: python src/extract_coords.py input/test_ball.mp4")
        sys.exit(1)

    video_path = Path(sys.argv[1])
    if not video_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다 → {video_path}")
        sys.exit(1)

    extract_coords(video_path)
