"""
OpenAI gpt-image-2 로 원본 텍스트 스타일을 유지한 새 텍스트 이미지 생성

OpenAI Python SDK 를 우회하고 requests 로 API 를 직접 호출한다.
(SDK 가 gpt-image-2 를 images.edit 에서 지원하지 않는 버전 호환 문제 회피)

초록 배경(#00FF00)으로 생성된 이미지를 크로마키 처리해 알파채널 PNG로 변환한다.

사용법:
    venv_sam2/bin/python src/generate_text_image.py \
        --reference-image output/video_text_masked.png \
        --new-text "새로운 텍스트" \
        --api-key sk-... \
        --output output/generated_text.png
"""

import argparse
import base64
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

API_URL = "https://api.openai.com/v1/images/edits"


def chroma_key_green(img_bgr: np.ndarray) -> np.ndarray:
    """초록 배경(#00FF00)을 투명 처리해 BGRA 배열을 반환한다."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    # H: 40-80 (초록), S/V: 100+ (채도·밝기 높은 순수 초록)
    mask = cv2.inRange(hsv,
                       np.array([40, 100, 100]),
                       np.array([80, 255, 255]))

    # 가장자리 부드럽게 (1px dilate)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask   = cv2.dilate(mask, kernel, iterations=1)

    bgra = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2BGRA)
    bgra[mask > 0, 3] = 0

    return bgra


def pick_output_size(width: int, height: int) -> str:
    """gpt-image-2 지원 사이즈 중 원본 비율에 가장 가까운 것을 반환한다.

    지원 사이즈: 1024x1024 (1:1), 1536x1024 (3:2), 1024x1536 (2:3)
    """
    ar = width / height if height > 0 else 1.0
    if ar >= 1.3:
        return "1536x1024"
    if ar <= 0.77:
        return "1024x1536"
    return "1024x1024"


def prepare_reference_bytes(img_path: Path, output_size: str) -> bytes:
    """참조 이미지를 출력 사이즈에 맞게 리사이즈한 PNG bytes로 변환한다."""
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"ERROR: 참조 이미지를 읽을 수 없습니다: {img_path}", flush=True)
        sys.exit(1)

    out_w, out_h = (int(v) for v in output_size.split("x"))
    resized = cv2.resize(img, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
    _, buf  = cv2.imencode(".png", resized)
    return buf.tobytes()


def run(reference_image: Path, new_text: str, api_key: str, output: Path) -> None:
    """OpenAI API 직접 호출 → 크로마키 처리 → RGBA PNG 저장."""
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"참조 이미지: {reference_image.name}", flush=True)
    print(f"새 텍스트: '{new_text}'", flush=True)

    # 참조 이미지 크기 측정 → 출력 사이즈 결정
    _ref = cv2.imread(str(reference_image))
    if _ref is None:
        print(f"ERROR: 참조 이미지를 읽을 수 없습니다: {reference_image}", flush=True)
        sys.exit(1)
    height, width = _ref.shape[:2]
    aspect_ratio  = width / height if height > 0 else 1.0
    output_size   = pick_output_size(width, height)
    print(f"참조 비율: {width}x{height} (aspect {aspect_ratio:.2f})", flush=True)
    print(f"출력 사이즈: {output_size}", flush=True)

    print("OpenAI API 호출 중...", flush=True)

    prompt = (
        f"Look at the reference image carefully. It contains text in a specific style. "
        f"Generate the same text visual style with new content: '{new_text}'. "
        f"Match the font, color, weight, glow, shadow, and outline effects exactly. "
        f"Background must be solid pure green (#00FF00) for chroma keying. "
        f"Output only the styled text on green background. No other elements."
    )

    img_bytes = prepare_reference_bytes(reference_image, output_size)

    t0 = time.time()

    # ── 5초마다 경과 시간 출력하는 백그라운드 스레드 ───────────
    import threading
    _stop = threading.Event()

    def _progress_printer():
        while not _stop.wait(5):
            print(f"API 호출 중... {int(time.time() - t0)}초 경과", flush=True)

    threading.Thread(target=_progress_printer, daemon=True).start()

    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"image": ("reference.png", img_bytes, "image/png")},
            data={
                "model":   "gpt-image-2",
                "prompt":  prompt,
                "size":    output_size,
                "quality": "medium",
                "n":       "1",
            },
            timeout=300,
        )
    except requests.exceptions.Timeout:
        _stop.set()
        print(
            "ERROR: OpenAI API 응답 지연 (5분 초과). "
            "네트워크 또는 OpenAI 서버 상태를 확인하거나, "
            "quality 를 'low' 로 낮춰 재시도해주세요.",
            flush=True,
        )
        sys.exit(1)
    finally:
        _stop.set()

    elapsed = time.time() - t0

    if resp.status_code != 200:
        print(f"ERROR: API 오류 {resp.status_code}: {resp.text}", flush=True)
        sys.exit(1)

    print(f"API 응답: {elapsed:.2f}s", flush=True)

    result   = resp.json()
    b64_data = result["data"][0]["b64_json"]
    arr      = np.frombuffer(base64.b64decode(b64_data), dtype=np.uint8)
    img_bgr  = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img_bgr is None:
        print("ERROR: 응답 이미지 디코딩 실패", flush=True)
        sys.exit(1)

    bgra        = chroma_key_green(img_bgr)
    text_pixels = int((bgra[:, :, 3] > 0).sum())
    cv2.imwrite(str(output), bgra)

    print(f"AI_IMAGE_READY: {output}", flush=True)
    print(f"텍스트 픽셀: {text_pixels}px  처리 시간: {elapsed:.2f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenAI gpt-image-2 텍스트 이미지 생성")
    parser.add_argument("--reference-image", required=True)
    parser.add_argument("--new-text",        required=True)
    parser.add_argument("--api-key",         required=True)
    parser.add_argument("--output",          required=True)
    args = parser.parse_args()

    try:
        run(Path(args.reference_image), args.new_text, args.api_key, Path(args.output))
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        import traceback; traceback.print_exc()
        sys.exit(1)
