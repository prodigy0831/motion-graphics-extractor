"""
객체 좌표 추출 스크립트

영상에서 지정한 색상 객체의 중심 좌표·크기를 프레임별로 추출해 JSON으로 저장한다.
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

# connected component 최소 면적 (노이즈 제거용)
MIN_COMPONENT_AREA = 20

# scale 이동평균 윈도우 크기
SCALE_SMOOTH_WINDOW = 5

# 수동 지정용 색 이름 → HSV 범위 매핑 테이블
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

DEFAULT_COLOR = "red"


# ── 영상 입출력 ───────────────────────────────────────────────────

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


# ── 객체 검출 ────────────────────────────────────────────────────

def detect_object_by_hsv(
    frame_bgr: np.ndarray,
    hsv_lower: np.ndarray,
    hsv_upper: np.ndarray,
    color_name: str = "",
) -> np.ndarray:
    """
    BGR 프레임에서 HSV 범위에 해당하는 픽셀을 찾아 이진 마스크를 반환한다.

    color_name이 "red"이면 H 170-180° 보조 범위를 자동으로 추가한다.
    """
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, hsv_lower, hsv_upper)

    if color_name == "red":
        lower2 = np.array([170, hsv_lower[1], hsv_lower[2]])
        upper2 = np.array([180, hsv_upper[1], hsv_upper[2]])
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lower2, upper2))

    return mask


def find_largest_component(
    mask: np.ndarray,
) -> Optional[Tuple[int, int, int, int, int]]:
    """
    이진 마스크에서 가장 큰 connected component를 찾아
    (중심x, 중심y, bounding_width, bounding_height, pixel_area)를 반환한다.

    connected components 방식은 moments 방식보다 노이즈에 강하다.
    여러 개의 작은 반점이 있어도 가장 큰 덩어리만 추적한다.
    면적이 MIN_COMPONENT_AREA 미만이면 None 반환.
    """
    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    if num_labels <= 1:
        return None  # 배경만 존재

    # label 0은 배경이므로 제외하고 면적 기준으로 가장 큰 컴포넌트 선택
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_idx = int(np.argmax(areas)) + 1  # +1: 배경 인덱스 보정

    area = int(stats[largest_idx, cv2.CC_STAT_AREA])
    if area < MIN_COMPONENT_AREA:
        return None

    cx = int(round(centroids[largest_idx][0]))
    cy = int(round(centroids[largest_idx][1]))
    w = int(stats[largest_idx, cv2.CC_STAT_WIDTH])
    h = int(stats[largest_idx, cv2.CC_STAT_HEIGHT])
    return cx, cy, w, h, area


# ── scale 계산 ────────────────────────────────────────────────────

def smooth_values(
    values: List[Optional[float]],
    window: int = SCALE_SMOOTH_WINDOW,
) -> List[Optional[float]]:
    """
    None이 섞인 수열에 중심 이동평균을 적용한다.

    None(미검출) 위치는 결과도 None으로 유지하며,
    이동평균 계산 시 None 이웃은 제외하고 유효값만 평균한다.
    """
    result: List[Optional[float]] = []
    half = window // 2
    for i, val in enumerate(values):
        if val is None:
            result.append(None)
            continue
        start = max(0, i - half)
        end = min(len(values), i + half + 1)
        neighbors = [values[j] for j in range(start, end) if values[j] is not None]
        result.append(sum(neighbors) / len(neighbors))
    return result


def calc_scales(smoothed_widths: List[Optional[float]]) -> List[Optional[float]]:
    """
    첫 유효 프레임의 width를 100%로 삼아 각 프레임의 scale(%)을 계산한다.

    기준 width가 0이거나 유효값이 없으면 전부 None 반환.
    """
    baseline = next((w for w in smoothed_widths if w is not None), None)
    if not baseline:
        return [None] * len(smoothed_widths)

    return [
        round((w / baseline) * 100.0, 1) if w is not None else None
        for w in smoothed_widths
    ]


# ── 시각화 ───────────────────────────────────────────────────────

def draw_cross_marker(frame: np.ndarray, x: int, y: int) -> np.ndarray:
    """프레임 위에 녹색 십자(+) 마커를 그려 반환한다."""
    cv2.line(frame, (x - MARKER_SIZE, y), (x + MARKER_SIZE, y),
             MARKER_COLOR, MARKER_THICKNESS, cv2.LINE_AA)
    cv2.line(frame, (x, y - MARKER_SIZE), (x, y + MARKER_SIZE),
             MARKER_COLOR, MARKER_THICKNESS, cv2.LINE_AA)
    return frame


# ── JSON 저장 ─────────────────────────────────────────────────────

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


# ── 색상 결정 ─────────────────────────────────────────────────────

def resolve_hsv(
    video_path: Path,
    color_arg: Optional[str],
    no_auto: bool,
) -> Tuple[np.ndarray, np.ndarray, str]:
    """
    색상 옵션에 따라 HSV 범위와 색 이름을 결정한다.

    우선순위: 수동 지정(--color) > 자동 감지 > 기본값(--no-auto)
    """
    if color_arg:
        color_name = color_arg.lower()
        if color_name not in COLOR_HSV_MAP:
            print(f"오류: 알 수 없는 색상 이름 '{color_arg}'")
            print(f"  사용 가능: {', '.join(COLOR_HSV_MAP.keys())}")
            sys.exit(1)
        lo, hi = COLOR_HSV_MAP[color_name]
        print(f"🎨 수동 지정 색상: {color_name} (HSV {lo[0]}-{hi[0]}/{lo[1]}-{hi[1]}/{lo[2]}-{hi[2]})")
        return np.array(lo), np.array(hi), color_name

    if no_auto:
        lo, hi = COLOR_HSV_MAP[DEFAULT_COLOR]
        print(f"🎨 자동 감지 꺼짐. 기본 색상 사용: {DEFAULT_COLOR}")
        return np.array(lo), np.array(hi), DEFAULT_COLOR

    try:
        from detect_color import detect_object_color
    except ImportError:
        print("경고: detect_color 모듈 로드 실패. 기본 빨강으로 진행합니다.")
        lo, hi = COLOR_HSV_MAP[DEFAULT_COLOR]
        return np.array(lo), np.array(hi), DEFAULT_COLOR

    result = detect_object_color(str(video_path))
    color_name = result["color_name"]
    confidence = result["confidence"]
    lo = result["hsv_lower"]
    hi = result["hsv_upper"]

    print(f"🎨 감지된 객체 색: {result['color_name_ko']} (confidence {confidence:.2f})")
    if confidence < 0.5:
        print(f"⚠️  신뢰도가 낮습니다. --color 옵션으로 직접 지정 권장.")

    return np.array(lo), np.array(hi), color_name


# ── 메인 추출 함수 ────────────────────────────────────────────────

def extract_coords(
    video_path: Path,
    hsv_lower: np.ndarray,
    hsv_upper: np.ndarray,
    color_name: str,
) -> None:
    """
    영상에서 지정 색상 객체의 좌표·크기를 추출하고 JSON과 디버그 영상을 저장한다.

    처리 흐름:
        1. 프레임별 객체 검출 (connected components) + 디버그 영상 작성
        2. bounding box width에 이동평균 적용 (노이즈 완화)
        3. scale 계산 (첫 유효 프레임 기준 %)
        4. JSON 저장
    """
    stem = video_path.stem
    json_path = OUTPUT_DIR / f"{stem}_coords.json"
    debug_path = OUTPUT_DIR / f"{stem}_debug.mp4"

    cap = open_video(video_path)
    info = get_video_info(cap)
    width, height, fps = info["width"], info["height"], info["fps"]
    total_frames = info["total_frames"]

    print(f"추출 시작: {video_path.name}")
    print(f"  해상도 {width}x{height}, {fps}fps, 총 {total_frames}프레임")

    OUTPUT_DIR.mkdir(exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (width, height))

    # 1단계: 프레임별 원시 검출 결과 수집 + 디버그 영상 작성
    raw_results: List[Optional[Tuple[int, int, int, int, int]]] = []

    for frame_idx in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            print(f"  경고: 프레임 {frame_idx}에서 영상이 끊겼습니다.")
            break

        if frame_idx % 50 == 0 or frame_idx == total_frames - 1:
            print(f"  프레임 {frame_idx + 1}/{total_frames} 처리 중...")

        mask = detect_object_by_hsv(frame, hsv_lower, hsv_upper, color_name)
        component = find_largest_component(mask)

        if component is not None:
            cx, cy, _w, _h, _area = component
            draw_cross_marker(frame, cx, cy)

        raw_results.append(component)
        writer.write(frame)

    cap.release()
    writer.release()

    # 2단계: 면적 기반 유효 지름으로 scale 계산
    # bounding box width는 anti-aliasing 경계 픽셀에 따라 흔들리므로
    # √(area/π)×2 (면적 기반 유효 지름)를 사용해 노이즈를 줄인다
    import math
    raw_sizes: List[Optional[float]] = [
        math.sqrt(r[4] / math.pi) * 2.0 if r is not None else None
        for r in raw_results
    ]
    smoothed_sizes = smooth_values(raw_sizes)
    scales = calc_scales(smoothed_sizes)

    # 3단계: frames_data 조합
    frames_data: List[dict] = []
    missing_count = 0

    for i, (component, scale) in enumerate(zip(raw_results, scales)):
        if component is None:
            if i < len(raw_results):  # 끊김 없이 순회한 프레임만 기록
                print(f"  경고: 프레임 {i}에서 객체를 찾지 못했습니다. (x, y = null)")
            frames_data.append({
                "frame": i, "x": None, "y": None,
                "width": None, "height": None, "scale": None,
            })
            missing_count += 1
        else:
            cx, cy, w, h, _area = component
            frames_data.append({
                "frame": i, "x": cx, "y": cy,
                "width": w, "height": h, "scale": scale,
            })

    save_coords_json(json_path, video_path.name, info, frames_data)

    # 결과 출력
    valid_scales = [s for s in scales if s is not None]
    scale_range = (max(valid_scales) - min(valid_scales)) if valid_scales else 0.0

    print(f"\n완료!")
    print(f"  좌표 JSON: {json_path}")
    print(f"  디버그 영상: {debug_path}")
    if missing_count > 0:
        print(f"  주의: {missing_count}개 프레임에서 객체를 찾지 못했습니다.")
    else:
        print(f"  전체 {len(frames_data)}프레임 좌표 추출 성공")
    print(f"  scale 변동폭: {scale_range:.1f}%  "
          f"({'키프레임 생성' if scale_range >= 5.0 else '변동 미미 → 키프레임 생략'} 예정)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="영상에서 객체 좌표·크기를 추출해 JSON과 AE용 디버그 영상을 생성합니다."
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
