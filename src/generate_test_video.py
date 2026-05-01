"""
테스트용 영상 생성 스크립트

검은 배경에 빨간 공이 직선으로 이동하는 mp4를 생성하고,
각 프레임의 정답 좌표를 JSON으로 함께 저장한다.
추후 객체 추적 결과와 비교해 정확도를 검증하는 데 사용.
"""

import cv2
import numpy as np
import json
from pathlib import Path


# 경로 설정 (이 파일 기준으로 상위 폴더의 input/)
BASE_DIR = Path(__file__).parent.parent
INPUT_DIR = BASE_DIR / "input"

OUTPUT_VIDEO = INPUT_DIR / "test_ball.mp4"
OUTPUT_JSON = INPUT_DIR / "test_ball_truth.json"

# 영상 스펙
WIDTH = 1280
HEIGHT = 720
FPS = 30
DURATION_SEC = 5
TOTAL_FRAMES = FPS * DURATION_SEC  # 150

# 객체 스펙
BALL_RADIUS = 30
BALL_COLOR = (0, 0, 255)  # BGR — 빨간색

# 시작점과 끝점
START_X, START_Y = 100, 100
END_X, END_Y = 1180, 620


def calc_ball_position(frame_idx: int, total_frames: int) -> tuple[int, int]:
    """
    프레임 인덱스에 따라 공의 중심 좌표를 계산한다.

    시작점에서 끝점까지 선형 보간(lerp)으로 이동.
    frame_idx는 0-based.
    """
    t = frame_idx / (total_frames - 1)  # 0.0 ~ 1.0
    x = int(START_X + (END_X - START_X) * t)
    y = int(START_Y + (END_Y - START_Y) * t)
    return x, y


def generate_test_video() -> None:
    """테스트 영상과 정답 JSON을 생성한다."""

    INPUT_DIR.mkdir(exist_ok=True)

    # mp4 인코더 설정
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(OUTPUT_VIDEO), fourcc, FPS, (WIDTH, HEIGHT))

    if not writer.isOpened():
        print("오류: 영상 파일을 생성할 수 없습니다. OpenCV 설치를 확인해주세요.")
        return

    truth_data: list[dict] = []

    print(f"영상 생성 시작: {OUTPUT_VIDEO.name}")
    print(f"  해상도 {WIDTH}x{HEIGHT}, {FPS}fps, {DURATION_SEC}초 ({TOTAL_FRAMES}프레임)")
    print(f"  이동 경로: ({START_X}, {START_Y}) → ({END_X}, {END_Y})")

    for frame_idx in range(TOTAL_FRAMES):
        # 진행 상황 출력 (30프레임마다)
        if frame_idx % 30 == 0 or frame_idx == TOTAL_FRAMES - 1:
            print(f"  프레임 {frame_idx + 1}/{TOTAL_FRAMES} 생성 중...")

        # 검은 배경 프레임 생성
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

        x, y = calc_ball_position(frame_idx, TOTAL_FRAMES)

        # 빨간 원 그리기 (안티앨리어싱 적용)
        cv2.circle(frame, (x, y), BALL_RADIUS, BALL_COLOR, thickness=-1, lineType=cv2.LINE_AA)

        writer.write(frame)

        # 정답 좌표 기록 (0-based 프레임 인덱스)
        truth_data.append({"frame": frame_idx, "x": x, "y": y})

    writer.release()

    # 정답 JSON 저장
    payload = {
        "video": OUTPUT_VIDEO.name,
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "total_frames": TOTAL_FRAMES,
        "ball_radius": BALL_RADIUS,
        "frames": truth_data,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n완료!")
    print(f"  영상: {OUTPUT_VIDEO}")
    print(f"  정답 JSON: {OUTPUT_JSON}")
    print(f"  총 {len(truth_data)}개 프레임 좌표 저장됨")


if __name__ == "__main__":
    generate_test_video()
