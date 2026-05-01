"""
JSON 좌표 → After Effects .jsx 스크립트 변환기

추출된 좌표 JSON을 읽어 AE에서 실행 가능한 ExtendScript(.jsx)를 생성한다.
AE에서 스크립트를 실행하면 null object에 좌표 키프레임이 자동으로 박힌다.

사용법:
    python src/json_to_jsx.py output/test_ball_coords.json
"""

import json
import sys
from pathlib import Path


def load_coords(json_path: Path) -> dict:
    """좌표 JSON 파일을 읽어 딕셔너리로 반환한다."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def build_keyframe_js_array(frames: list[dict], fps: float) -> str:
    """
    프레임 데이터를 AE ExtendScript용 JavaScript 배열 리터럴 문자열로 변환한다.

    null 좌표(객체 미검출 프레임)는 건너뛰고 유효한 좌표만 포함한다.
    """
    lines = []
    for item in frames:
        x = item["x"]
        y = item["y"]
        if x is None or y is None:
            continue  # 미검출 프레임은 키프레임 생략
        time_sec = item["frame"] / fps
        lines.append(f"  {{frame: {item['frame']}, time: {time_sec:.6f}, x: {x}, y: {y}}}")

    return "[\n" + ",\n".join(lines) + "\n]"


def build_jsx_script(data: dict) -> str:
    """
    좌표 데이터를 바탕으로 AE ExtendScript 전체 코드를 생성해 반환한다.

    생성된 스크립트는 즉시 실행 함수(IIFE) 형태로 감싸
    전역 스코프 오염을 방지한다.
    """
    video_name: str = data["video"]
    fps: float = data["fps"]
    width: int = data["width"]
    height: int = data["height"]
    frames: list[dict] = data["frames"]

    # null 레이어 이름 (확장자 제거)
    stem = Path(video_name).stem
    layer_name = f"Tracked_{stem}"

    # 유효 키프레임 수 계산
    valid_count = sum(1 for f in frames if f["x"] is not None)

    keyframes_js = build_keyframe_js_array(frames, fps)

    # .jsx 본문 생성
    jsx = f"""\
// ============================================================
// 이 스크립트는 모션그래픽 추출기로 자동 생성됨
// 원본 영상: {video_name}
// 영상 해상도: {width}x{height}  /  FPS: {fps}
// 유효 키프레임: {valid_count}개
//
// 사용법:
//   AE → File → Scripts → Run Script File → 이 파일 선택
//   ※ 스크립트 실행 전 대상 컴포지션을 활성화(열어둔) 상태여야 합니다.
// ============================================================

(function () {{
    // ── 1. 활성 컴포지션 확인 ────────────────────────────────
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {{
        alert("활성화된 컴포지션이 없습니다.\\n컴포지션을 열고 다시 실행해주세요.");
        return;
    }}

    // ── 2. 해상도 불일치 경고 ────────────────────────────────
    if (comp.width !== {width} || comp.height !== {height}) {{
        alert(
            "주의: 컴포지션 해상도(" + comp.width + "x" + comp.height + ")가\\n" +
            "원본 영상 해상도({width}x{height})와 다릅니다.\\n\\n" +
            "좌표가 정확하려면 컴포지션 해상도를 {width}x{height}로 맞춰주세요.\\n" +
            "(Composition → Composition Settings → Width/Height)"
        );
    }}

    // ── 3. null object 레이어 생성 ───────────────────────────
    var nullLayer = comp.layers.addNull();
    nullLayer.name = "{layer_name}";

    var position = nullLayer.property("Position");

    // ── 4. 키프레임 데이터 ───────────────────────────────────
    var keyframes = {keyframes_js};

    // ── 5. 키프레임 적용 ────────────────────────────────────
    app.beginUndoGroup("모션 키프레임 적용: {layer_name}");

    for (var i = 0; i < keyframes.length; i++) {{
        var kf = keyframes[i];
        position.setValueAtTime(kf.time, [kf.x, kf.y]);
    }}

    // ── 6. 선형 보간 설정 (키프레임이 튀지 않게) ────────────
    for (var k = 1; k <= position.numKeys; k++) {{
        position.setInterpolationTypeAtKey(
            k,
            KeyframeInterpolationType.LINEAR,
            KeyframeInterpolationType.LINEAR
        );
    }}

    app.endUndoGroup();

    // ── 7. 완료 알림 ────────────────────────────────────────
    alert(
        "키프레임 " + keyframes.length + "개 적용 완료!\\n" +
        "레이어 이름: {layer_name}\\n\\n" +
        "※ 컴포지션 프레임 레이트가 {fps}fps인지 확인하세요."
    );
}})();
"""
    return jsx


def convert(json_path: Path) -> None:
    """JSON 좌표 파일을 읽어 .jsx 파일로 변환한다."""
    # 출력 경로: 같은 폴더에 같은 이름, 확장자만 .jsx
    jsx_path = json_path.with_name(json_path.stem.replace("_coords", "") + ".jsx")

    print(f"변환 시작: {json_path.name}")

    data = load_coords(json_path)
    total = len(data["frames"])
    valid = sum(1 for f in data["frames"] if f["x"] is not None)

    if valid == 0:
        print("오류: 유효한 좌표 데이터가 없습니다. 추출 결과를 확인해주세요.")
        sys.exit(1)

    if valid < total:
        print(f"  경고: {total - valid}개 프레임은 좌표가 없어 키프레임에서 제외됩니다.")

    jsx_code = build_jsx_script(data)

    with open(jsx_path, "w", encoding="utf-8") as f:
        f.write(jsx_code)

    print(f"\n완료!")
    print(f"  출력 파일: {jsx_path}")
    print(f"  키프레임 수: {valid}개  (전체 {total}프레임 중)")
    print(f"\nAE 사용법:")
    print(f"  File → Scripts → Run Script File → {jsx_path.name} 선택")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python src/json_to_jsx.py <좌표 JSON 경로>")
        print("  예시: python src/json_to_jsx.py output/test_ball_coords.json")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다 → {json_path}")
        sys.exit(1)

    convert(json_path)
