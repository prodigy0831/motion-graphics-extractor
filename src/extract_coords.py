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
import math
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

# 원형 판정 aspect ratio 범위 (w/h 가 이 범위 안이면 원형으로 간주)
CIRCLE_ASPECT_RATIO_MIN = 0.85
CIRCLE_ASPECT_RATIO_MAX = 1.15

# 회전 wrap-around 보정 임계값 (도)
# w≥h 정규화 후 각도 범위가 [-90, 90)이 되어
# 한 바퀴 경계에서 ±178° 수준의 점프가 발생 → ±90 기준으로 보정
ROTATION_WRAP_THRESHOLD = 90.0

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


# ── 회전 계산 ────────────────────────────────────────────────────

def calc_raw_rotation(mask: np.ndarray) -> Optional[Tuple[float, bool]]:
    """
    마스크에서 가장 큰 컨투어에 cv2.minAreaRect를 적용해
    (raw_angle, is_circular)를 반환한다.

    장축이 항상 w가 되도록 정규화하면 각도 범위가 [-90, 90)이 된다.
    이 범위에서 원 한 바퀴 회전 시 ±178° 점프가 발생하고,
    ROTATION_WRAP_THRESHOLD(90°) 초과 여부로 감지·보정한다.
    컨투어가 없거나 너무 작으면 None 반환.
    """
    contours, _ = cv2.findContours(
        mask.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < MIN_COMPONENT_AREA:
        return None

    (_, _), (w, h), angle = cv2.minAreaRect(largest)

    # 장축이 항상 w가 되도록 정규화 → 각도 범위 [-90, 90)
    if w < h:
        w, h = h, w
        angle += 90.0

    aspect_ratio = w / h if h > 0 else 1.0
    is_circular = CIRCLE_ASPECT_RATIO_MIN <= aspect_ratio <= CIRCLE_ASPECT_RATIO_MAX
    return angle, is_circular


def accumulate_rotations_from_ref(
    raw_angles: List[Optional[float]],
    ref_idx: int,
) -> List[Optional[float]]:
    """
    기준 프레임(ref_idx)을 0°로 하여 전후 프레임의 누적 회전 각도를 계산한다.

    순방향(ref_idx → 끝)과 역방향(ref_idx → 처음)으로 각각 누적하므로
    객체가 화면 밖에서 진입하는 영상도 올바른 기준으로 정규화된다.
    기준 프레임의 raw_angle이 없으면 None 리스트를 반환한다.
    """
    n = len(raw_angles)
    result: List[Optional[float]] = [None] * n

    ref_angle = raw_angles[ref_idx]
    if ref_angle is None:
        return result

    result[ref_idx] = 0.0

    # 순방향: ref_idx+1 → 끝
    accumulated = 0.0
    prev_raw = ref_angle
    for i in range(ref_idx + 1, n):
        angle = raw_angles[i]
        if angle is None:
            continue
        diff = angle - prev_raw
        if diff > ROTATION_WRAP_THRESHOLD:
            diff -= 180.0
        elif diff < -ROTATION_WRAP_THRESHOLD:
            diff += 180.0
        accumulated += diff
        prev_raw = angle
        result[i] = round(accumulated, 1)

    # 역방향: ref_idx-1 → 0
    # diff_forward: 프레임 i → i+1 방향의 변화량 = prev_raw(=i+1) - angle(=i)
    # 역방향 누적이므로 diff_forward를 뺀다
    accumulated = 0.0
    prev_raw = ref_angle
    for i in range(ref_idx - 1, -1, -1):
        angle = raw_angles[i]
        if angle is None:
            continue
        diff_forward = prev_raw - angle
        if diff_forward > ROTATION_WRAP_THRESHOLD:
            diff_forward -= 180.0
        elif diff_forward < -ROTATION_WRAP_THRESHOLD:
            diff_forward += 180.0
        accumulated -= diff_forward
        prev_raw = angle
        result[i] = round(accumulated, 1)

    return result


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


def calc_scales(
    smoothed_widths: List[Optional[float]],
    baseline: Optional[float] = None,
) -> List[Optional[float]]:
    """
    지정된 baseline을 100%로 삼아 각 프레임의 scale(%)을 계산한다.

    baseline이 None이면 첫 유효 프레임 값을 사용(하위 호환).
    baseline이 0이거나 유효값이 없으면 전부 None 반환.
    """
    actual_baseline = baseline if baseline is not None else \
        next((w for w in smoothed_widths if w is not None), None)
    if not actual_baseline:
        return [None] * len(smoothed_widths)

    return [
        round((w / actual_baseline) * 100.0, 1) if w is not None else None
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


# ── 기준 프레임 선택 ──────────────────────────────────────────────

REF_SCAN_FRAMES = 30      # 기준 프레임을 탐색할 앞부분 프레임 수
AREA_VALID_RATIO = 0.5    # 기준 면적 대비 이 비율 미만이면 rotation 신뢰 불가
                          # (화면 가장자리에서 잘린 슬리버는 minAreaRect 각도가 왜곡됨)


def find_reference_frame(
    video_path: Path,
    hsv_lower: np.ndarray,
    hsv_upper: np.ndarray,
    color_name: str,
) -> Tuple[int, float]:
    """
    처음 REF_SCAN_FRAMES 프레임 중 객체 면적이 가장 큰 프레임을 기준으로 선택한다.

    객체가 화면 밖에서 진입하는 경우, 첫 프레임은 잘린 조각이라 면적이 작다.
    가장 큰 면적 = 객체가 화면에 완전히 들어온 상태라고 가정한다.
    반환: (기준_프레임_인덱스, 기준_픽셀_면적)
    검출 실패 시 (0, 0.0) 반환.
    """
    cap = cv2.VideoCapture(str(video_path))
    best_idx = 0
    best_area = 0.0

    for i in range(REF_SCAN_FRAMES):
        ret, frame = cap.read()
        if not ret:
            break
        mask = detect_object_by_hsv(frame, hsv_lower, hsv_upper, color_name)
        component = find_largest_component(mask)
        if component is not None:
            area = float(component[4])
            if area > best_area:
                best_area = area
                best_idx = i

    cap.release()
    return best_idx, best_area


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
    영상에서 지정 색상 객체의 좌표·크기·회전을 추출하고 JSON과 디버그 영상을 저장한다.

    처리 흐름:
        1. 프레임별 객체 검출 (connected components + minAreaRect) + 디버그 영상 작성
        2. 면적 기반 유효 지름으로 scale 계산 (이동평균 포함)
        3. 원형 여부 판정 → 비원형만 누적 회전 계산
        4. JSON 저장
    """
    stem = video_path.stem
    json_path = OUTPUT_DIR / f"{stem}_coords.json"
    debug_path = OUTPUT_DIR / f"{stem}_debug.mp4"

    cap = open_video(video_path)
    info = get_video_info(cap)
    width, height, fps = info["width"], info["height"], info["fps"]
    total_frames = info["total_frames"]

    # 기준 프레임 선택 (scale·rotation 기준점)
    ref_idx, ref_area = find_reference_frame(video_path, hsv_lower, hsv_upper, color_name)
    ref_size = math.sqrt(ref_area / math.pi) * 2.0 if ref_area > 0 else None

    print(f"추출 시작: {video_path.name}")
    print(f"  해상도 {width}x{height}, {fps}fps, 총 {total_frames}프레임")
    print(f"  기준 프레임: {ref_idx} (면적 {int(ref_area)}px²)")

    OUTPUT_DIR.mkdir(exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(debug_path), fourcc, fps, (width, height))

    # 1단계: 프레임별 원시 검출 결과 수집 + 디버그 영상 작성
    raw_results: List[Optional[Tuple[int, int, int, int, int]]] = []
    raw_rot_results: List[Optional[Tuple[float, bool]]] = []

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
            rot_result = calc_raw_rotation(mask)
        else:
            rot_result = None

        raw_results.append(component)
        raw_rot_results.append(rot_result)
        writer.write(frame)

    cap.release()
    writer.release()

    # 2단계: 면적 기반 유효 지름으로 scale 계산
    # bounding box width는 anti-aliasing 경계 픽셀에 따라 흔들리므로
    # √(area/π)×2 (면적 기반 유효 지름)를 사용해 노이즈를 줄인다
    raw_sizes: List[Optional[float]] = [
        math.sqrt(r[4] / math.pi) * 2.0 if r is not None else None
        for r in raw_results
    ]
    smoothed_sizes = smooth_values(raw_sizes)
    scales = calc_scales(smoothed_sizes, baseline=ref_size)

    # 3단계: 면적이 작은 프레임의 rotation 제외
    # 기준 면적의 50% 미만 = 객체가 화면 가장자리에 일부만 걸친 상태
    # 이 경우 minAreaRect의 w/h가 역전되어 각도가 90° 뒤집히므로 제외
    if ref_area > 0:
        filtered_rot: List[Optional[Tuple[float, bool]]] = []
        for comp, rot in zip(raw_results, raw_rot_results):
            if comp is not None and rot is not None:
                if comp[4] / ref_area < AREA_VALID_RATIO:
                    rot = None  # 잘린 조각은 rotation 신뢰 불가
            filtered_rot.append(rot)
    else:
        filtered_rot = raw_rot_results

    # 원형 여부 판정 (과반수 투표)
    # 단일 프레임 판정은 노이즈에 취약하므로 모든 프레임의 결과를 집계한다.
    # 50% 이상의 프레임이 원형으로 분류되면 원형 객체로 간주한다.
    circular_votes = [r[1] for r in filtered_rot if r is not None]
    if circular_votes:
        is_circular = (sum(circular_votes) / len(circular_votes)) >= 0.5
    else:
        is_circular = True

    if is_circular:
        print("  원형 객체 감지됨, 회전 추출 생략")
        rotations: List[Optional[float]] = [
            0.0 if r is not None else None for r in filtered_rot
        ]
    else:
        raw_angles: List[Optional[float]] = [
            r[0] if r is not None else None for r in filtered_rot
        ]
        rotations = accumulate_rotations_from_ref(raw_angles, ref_idx)

    # 4단계: frames_data 조합
    frames_data: List[dict] = []
    missing_count = 0

    for i, (component, scale, rotation) in enumerate(zip(raw_results, scales, rotations)):
        if component is None:
            print(f"  경고: 프레임 {i}에서 객체를 찾지 못했습니다. (x, y = null)")
            frames_data.append({
                "frame": i, "x": None, "y": None,
                "width": None, "height": None, "scale": None, "rotation": None,
            })
            missing_count += 1
        else:
            cx, cy, w, h, _area = component
            frames_data.append({
                "frame": i, "x": cx, "y": cy,
                "width": w, "height": h, "scale": scale, "rotation": rotation,
            })

    save_coords_json(json_path, video_path.name, info, frames_data)

    # 결과 출력
    valid_scales = [s for s in scales if s is not None]
    scale_range = (max(valid_scales) - min(valid_scales)) if valid_scales else 0.0
    valid_rots = [r for r in rotations if r is not None]
    rot_range = (max(valid_rots) - min(valid_rots)) if valid_rots else 0.0

    print(f"\n완료!")
    print(f"  좌표 JSON: {json_path}")
    print(f"  디버그 영상: {debug_path}")
    if missing_count > 0:
        print(f"  주의: {missing_count}개 프레임에서 객체를 찾지 못했습니다.")
    else:
        print(f"  전체 {len(frames_data)}프레임 좌표 추출 성공")
    print(f"  scale 변동폭:    {scale_range:.1f}%  "
          f"({'키프레임 생성' if scale_range >= 5.0 else '생략'} 예정)")
    print(f"  rotation 변동폭: {rot_range:.1f}°  "
          f"({'키프레임 생성' if rot_range >= 1.0 else '생략'} 예정)")


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
