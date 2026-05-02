"""
객체 색상 자동 감지 모듈

영상의 첫 30프레임을 샘플링해 K-means 클러스터링으로
배경색과 객체색을 분리하고, 객체 색상을 자동으로 판별한다.

사용 예:
    from detect_color import detect_object_color
    result = detect_object_color("input/video.mp4")
    # {"color_name": "red", "hsv_lower": [0, 120, 70], "hsv_upper": [10, 255, 255], "confidence": 0.94}
"""

import cv2
import numpy as np
import warnings
from sklearn.cluster import KMeans
from pathlib import Path
from typing import Optional


# 샘플링 파라미터
N_SAMPLE_FRAMES = 30       # 분석할 프레임 수
PIXELS_PER_FRAME = 1000    # 프레임당 무작위 샘플 픽셀 수
N_CLUSTERS = 2             # K-means 클러스터 수 (배경 + 객체)
HSV_RANGE_MARGIN = 15      # HSV 범위 계산 시 여유 폭

# HSV 색 이름 매핑 (OpenCV H 범위: 0-180)
COLOR_MAP = [
    ("red",    (0,   10)),   # 빨강 (0° 근처, 실제로는 dual range)
    ("orange", (10,  22)),   # 주황
    ("yellow", (22,  38)),   # 노랑
    ("green",  (38,  85)),   # 초록
    ("cyan",   (85, 100)),   # 청록
    ("blue",   (100, 130)),  # 파랑
    ("purple", (130, 155)),  # 보라
    ("pink",   (155, 170)),  # 분홍
    ("red",    (170, 180)),  # 빨강 (180° 근처)
]

COLOR_NAME_KO = {
    "red":    "빨강",
    "orange": "주황",
    "yellow": "노랑",
    "green":  "초록",
    "cyan":   "청록",
    "blue":   "파랑",
    "purple": "보라",
    "pink":   "분홍",
    "white":  "흰색",
    "black":  "검정",
    "gray":   "회색",
}


# ── 1. 프레임 샘플링 ──────────────────────────────────────────────

def sample_frames(video_path: str, n_frames: int = N_SAMPLE_FRAMES) -> list:
    """
    영상 앞부분에서 n_frames 개의 프레임을 순서대로 읽어 반환한다.

    프레임 수가 n_frames보다 적으면 가능한 만큼만 반환.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"영상 파일을 열 수 없습니다: {video_path}")

    frames = []
    while len(frames) < n_frames:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)

    cap.release()
    return frames


# ── 2. 픽셀 수집 ─────────────────────────────────────────────────

# 채도 임계값: 이 값 이상이면 "객체 후보" 픽셀로 간주
SAT_THRESHOLD = 70
# 카테고리별 프레임당 최대 샘플 수 (균형 유지)
MAX_HI_SAT_PER_FRAME = 500
MAX_BG_PER_FRAME = 500


def collect_hsv_pixels(
    frames: list,
    pixels_per_frame: int = PIXELS_PER_FRAME,
) -> np.ndarray:
    """
    프레임 목록을 HSV로 변환한 뒤 픽셀을 수집해 (N, 3) 배열로 반환한다.

    고채도 픽셀(객체)과 저채도 픽셀(배경)을 각각 최대 500개씩 균등 샘플링한다.
    고채도 픽셀이 소수여도(작은 공 등) 전부 포함하고,
    많아도 500개로 캡을 씌워 K-means가 객체 내부를 양분하지 않게 한다.
    """
    rng = np.random.default_rng(42)
    all_pixels = []

    for frame in frames:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        flat = hsv.reshape(-1, 3).astype(np.float64)

        sat = flat[:, 1]
        hi_sat = flat[sat >= SAT_THRESHOLD]
        lo_sat = flat[sat < SAT_THRESHOLD]

        # 고채도: 500개 이하면 전부, 초과하면 무작위 500개
        n_hi = min(MAX_HI_SAT_PER_FRAME, len(hi_sat))
        if n_hi > 0:
            hi_idx = rng.choice(len(hi_sat), size=n_hi, replace=False)
            all_pixels.append(hi_sat[hi_idx])

        # 배경: 무작위 500개
        n_bg = min(MAX_BG_PER_FRAME, len(lo_sat))
        if n_bg > 0:
            bg_idx = rng.choice(len(lo_sat), size=n_bg, replace=False)
            all_pixels.append(lo_sat[bg_idx])

    return np.vstack(all_pixels)


# ── 3. K-means 클러스터링 ─────────────────────────────────────────

def cluster_hsv_pixels(
    pixels: np.ndarray,
    k: int = N_CLUSTERS,
) -> tuple:
    """
    S(채도)·V(명도) 2차원 공간에서 K-means를 수행해
    (KMeans 모델, 레이블 배열)을 반환한다.

    H(색조)를 제외하는 이유: 빨강처럼 H가 0°와 360° 양쪽에 걸치는 색상은
    H축 클러스터링이 부정확하기 때문에 S·V 분리로 배경/객체를 구분한다.
    """
    sv = pixels[:, 1:]  # S, V 채널만 사용
    # sklearn k-means++ 초기화에서 간헐적으로 발생하는 수치 경고 억제
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(sv)
    return kmeans, labels


# ── 4. 객체 클러스터 선택 ─────────────────────────────────────────

def select_object_cluster(
    kmeans: KMeans,
    labels: np.ndarray,
    pixels: np.ndarray,
) -> tuple:
    """
    채도(S)가 더 높은 클러스터를 객체로 선정한다.

    배경은 일반적으로 채도가 낮고, 추적 대상 객체는 채도가 높다는
    가정에 기반한다. 반환: (객체 클러스터 인덱스, 객체 픽셀 배열).
    """
    centers_sv = kmeans.cluster_centers_  # (k, 2) — S, V 순서
    object_idx = int(np.argmax(centers_sv[:, 0]))  # S가 가장 높은 클러스터
    object_pixels = pixels[labels == object_idx]
    return object_idx, object_pixels


# ── 5. 신뢰도 계산 ───────────────────────────────────────────────

def calc_confidence(kmeans: KMeans) -> float:
    """
    두 클러스터 간 채도 차이를 바탕으로 감지 신뢰도(0.0~1.0)를 계산한다.

    채도 차이가 클수록 배경과 객체가 명확하게 분리됐다는 뜻이므로
    신뢰도가 높다. 차이가 200 이상이면 1.0으로 클리핑.
    """
    centers_sv = kmeans.cluster_centers_
    s_values = centers_sv[:, 0]
    gap = float(abs(s_values[0] - s_values[1]))
    return round(min(1.0, gap / 200.0), 2)


# ── 6. HSV 범위 계산 ─────────────────────────────────────────────

def calc_hsv_range(
    object_pixels: np.ndarray,
    color_name: str,
    margin: int = HSV_RANGE_MARGIN,
) -> tuple:
    """
    객체 픽셀의 5~95 퍼센타일 기반으로 HSV 탐지 범위를 계산한다.

    빨강은 H가 0° 근처에 분포하므로 lower=[0,s,v], upper=[10,s,v]로 고정한다.
    실제 추적 시 170~180° 보조 범위는 호출 측에서 color_name == "red"를
    확인해 별도로 추가해야 한다.
    """
    h = object_pixels[:, 0]
    s = object_pixels[:, 1]
    v = object_pixels[:, 2]

    s_lower = max(0,   int(np.percentile(s, 5))  - margin)
    s_upper = min(255, int(np.percentile(s, 95)) + margin)
    v_lower = max(0,   int(np.percentile(v, 5))  - margin)
    v_upper = min(255, int(np.percentile(v, 95)) + margin)

    if color_name == "red":
        # 빨강은 H wrap-around 처리: 항상 0~10으로 고정
        h_lower, h_upper = 0, 10
    else:
        h_lower = max(0,   int(np.percentile(h, 5))  - margin)
        h_upper = min(180, int(np.percentile(h, 95)) + margin)

    return [h_lower, s_lower, v_lower], [h_upper, s_upper, v_upper]


# ── 7. 색 이름 매핑 ──────────────────────────────────────────────

def map_color_name(object_pixels: np.ndarray) -> str:
    """
    객체 픽셀의 HSV 평균값을 사람이 읽을 수 있는 영문 색 이름으로 변환한다.

    무채색(흰색·검정·회색)은 V·S 기준으로 먼저 판별하고,
    유채색은 H 평균값을 COLOR_MAP과 대조해 결정한다.
    """
    h_vals = object_pixels[:, 0]
    s_mean = float(np.mean(object_pixels[:, 1]))
    v_mean = float(np.mean(object_pixels[:, 2]))

    # 무채색 판별
    if v_mean < 50:
        return "black"
    if s_mean < 40:
        return "white" if v_mean > 200 else "gray"

    # 빨강 wrap-around 처리: H 값을 0° 기준으로 통일
    h_wrapped = np.where(h_vals > 90, h_vals - 180, h_vals)
    h_mean = float(np.mean(h_wrapped))
    # 음수로 내려간 경우 다시 양수 영역으로
    if h_mean < 0:
        h_mean += 180

    for name, (h_low, h_high) in COLOR_MAP:
        if h_low <= h_mean < h_high:
            return name

    return "unknown"


# ── 8. 메인 감지 함수 ────────────────────────────────────────────

def detect_object_color(video_path: str) -> dict:
    """
    영상에서 배경과 구분되는 주요 객체의 색상을 자동으로 감지한다.

    내부 동작:
        1. 첫 30프레임 샘플링
        2. HSV 픽셀 무작위 수집
        3. S·V 기반 K-means(k=2)로 배경/객체 분리
        4. 채도 높은 클러스터 = 객체로 판정
        5. H 평균으로 색 이름 결정, 퍼센타일로 HSV 범위 계산

    반환 예:
        {
            "color_name": "red",
            "color_name_ko": "빨강",
            "hsv_lower": [0, 120, 70],
            "hsv_upper": [10, 255, 255],
            "confidence": 0.94
        }
    """
    frames = sample_frames(video_path)
    if not frames:
        raise ValueError(f"프레임을 읽을 수 없습니다: {video_path}")

    pixels = collect_hsv_pixels(frames)
    kmeans, labels = cluster_hsv_pixels(pixels)
    _, object_pixels = select_object_cluster(kmeans, labels, pixels)

    confidence = calc_confidence(kmeans)
    color_name = map_color_name(object_pixels)
    hsv_lower, hsv_upper = calc_hsv_range(object_pixels, color_name)

    return {
        "color_name": color_name,
        "color_name_ko": COLOR_NAME_KO.get(color_name, color_name),
        "hsv_lower": hsv_lower,
        "hsv_upper": hsv_upper,
        "confidence": confidence,
    }


# ── 단독 테스트 ──────────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent.parent
    test_videos = [
        BASE_DIR / "input" / "test_ball.mp4",
        BASE_DIR / "input" / "kling_test.mp4",
        BASE_DIR / "input" / "kling_test2.mp4",
    ]

    for video_path in test_videos:
        if not video_path.exists():
            print(f"[{video_path.name}] 파일 없음, 건너뜀")
            continue

        result = detect_object_color(str(video_path))

        lo = result["hsv_lower"]
        hi = result["hsv_upper"]
        hsv_str = f"HSV {lo[0]}-{hi[0]}/{lo[1]}-{hi[1]}/{lo[2]}-{hi[2]}"

        print(
            f"[{video_path.name}] 감지 결과: "
            f"{result['color_name_ko']} ({hsv_str}), "
            f"confidence {result['confidence']:.2f}"
        )
