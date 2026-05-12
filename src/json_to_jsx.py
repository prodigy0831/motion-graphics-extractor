"""
JSON 좌표 → After Effects .jsx 스크립트 변환기

추출된 좌표 JSON을 읽어 AE에서 실행 가능한 ExtendScript(.jsx)를 생성한다.
Position 키프레임 외에 scale 변동폭이 5% 이상이면 Scale 키프레임도 생성한다.

사용법:
    python src/json_to_jsx.py output/test_ball_coords.json
"""

import json
import sys
from pathlib import Path
from typing import List

from simplify_path import simplify_motion_path


# scale 변동폭이 이 값(%) 이상이면 Scale 키프레임을 생성한다
SCALE_KEYFRAME_THRESHOLD = 5.0

# rotation 변동폭이 이 값(°) 이상이면 Rotation 키프레임을 생성한다
ROTATION_KEYFRAME_THRESHOLD = 1.0


def load_coords(json_path: Path) -> dict:
    """좌표 JSON 파일을 읽어 딕셔너리로 반환한다."""
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def build_position_js_array(frames: List[dict], fps: float) -> str:
    """
    프레임 데이터를 Position 키프레임용 JavaScript 배열 리터럴로 변환한다.

    x 또는 y가 None인 프레임(미검출)은 건너뛴다.
    """
    lines = []
    for item in frames:
        if item["x"] is None or item["y"] is None:
            continue
        time_sec = item["frame"] / fps
        lines.append(
            f"  {{frame: {item['frame']}, time: {time_sec:.6f}, x: {item['x']}, y: {item['y']}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def build_bezier_position_js_array(keyframes: List[dict]) -> str:
    """단순화된 베지어 키프레임을 JavaScript 배열 리터럴로 변환한다."""
    lines = []
    for kf in keyframes:
        lines.append(
            f"  {{frame: {kf['frame']}, time: {kf['time']:.6f}, "
            f"x: {kf['x']}, y: {kf['y']}, "
            f"in_x: {kf['in_x']:.4f}, in_y: {kf['in_y']:.4f}, "
            f"out_x: {kf['out_x']:.4f}, out_y: {kf['out_y']:.4f}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def build_scale_js_array(frames: List[dict], fps: float) -> str:
    """
    프레임 데이터를 Scale 키프레임용 JavaScript 배열 리터럴로 변환한다.

    scale이 None인 프레임은 건너뛴다.
    """
    lines = []
    for item in frames:
        if item.get("scale") is None:
            continue
        time_sec = item["frame"] / fps
        lines.append(
            f"  {{frame: {item['frame']}, time: {time_sec:.6f}, scale: {item['scale']}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def build_rotation_js_array(frames: List[dict], fps: float) -> str:
    """
    프레임 데이터를 Rotation 키프레임용 JavaScript 배열 리터럴로 변환한다.

    rotation이 None인 프레임은 건너뛴다.
    """
    lines = []
    for item in frames:
        if item.get("rotation") is None:
            continue
        time_sec = item["frame"] / fps
        lines.append(
            f"  {{frame: {item['frame']}, time: {time_sec:.6f}, rotation: {item['rotation']}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def should_add_rotation_keyframes(frames: List[dict]) -> bool:
    """
    rotation 변동폭이 임계값(1°) 이상인지 확인한다.

    원형 객체는 rotation이 모두 0이므로 자동으로 생략된다.
    """
    rotations = [f["rotation"] for f in frames if f.get("rotation") is not None]
    if len(rotations) < 2:
        return False
    return (max(rotations) - min(rotations)) >= ROTATION_KEYFRAME_THRESHOLD


def should_add_scale_keyframes(frames: List[dict]) -> bool:
    """
    scale 변동폭이 임계값(5%) 이상인지 확인한다.

    scale 데이터가 없거나 변동이 미미하면 False를 반환해
    불필요한 Scale 키프레임 생성을 생략한다.
    """
    scales = [f["scale"] for f in frames if f.get("scale") is not None]
    if len(scales) < 2:
        return False
    return (max(scales) - min(scales)) >= SCALE_KEYFRAME_THRESHOLD


def build_jsx_script(data: dict, simplify_result: dict = None) -> str:
    """
    좌표·크기 데이터를 바탕으로 AE ExtendScript 전체 코드를 생성해 반환한다.

    simplify_result가 주어지면 Position을 베지어 단순화 키프레임으로 생성한다.
    """
    video_name: str = data["video"]
    fps: float = data["fps"]
    width: int = data["width"]
    height: int = data["height"]
    frames: List[dict] = data["frames"]

    stem = Path(video_name).stem
    layer_name = f"Tracked_{stem}"

    valid_count = sum(1 for f in frames if f["x"] is not None)
    add_scale = should_add_scale_keyframes(frames)
    add_rotation = should_add_rotation_keyframes(frames)

    # Scale 관련 변수 계산
    scales = [f["scale"] for f in frames if f.get("scale") is not None]
    scale_range = (max(scales) - min(scales)) if scales else 0.0

    # Rotation 관련 변수 계산
    rotations = [f["rotation"] for f in frames if f.get("rotation") is not None]
    rot_range = (max(rotations) - min(rotations)) if rotations else 0.0

    # Position 블록 — 베지어 단순화 or 선형 원본
    if simplify_result is not None and simplify_result['simplified_count'] > 0:
        simplified_count = simplify_result['simplified_count']
        tolerance_px     = simplify_result['tolerance_px']
        position_js      = build_bezier_position_js_array(simplify_result['keyframes'])
        pos_data_comment = (
            f"// ── 4. Position 키프레임 (베지어 단순화: {valid_count}→{simplified_count}개, "
            f"허용 오차 {tolerance_px}px) ─────────────"
        )
        pos_apply_block = f"""\
    // ── 5. Position 키프레임 적용 (베지어 보간) ──────────────
    var position = nullLayer.property("Position");
    for (var i = 0; i < keyframes.length; i++) {{
        var kf = keyframes[i];
        position.setValueAtTime(kf.time, [kf.x, kf.y]);
    }}
    for (var k = 1; k <= position.numKeys; k++) {{
        position.setInterpolationTypeAtKey(
            k, KeyframeInterpolationType.BEZIER, KeyframeInterpolationType.BEZIER
        );
        var kf = keyframes[k - 1];
        position.setSpatialTangentsAtKey(k, [kf.in_x, kf.in_y, 0], [kf.out_x, kf.out_y, 0]);
    }}"""
        kf_count_display = simplified_count
        pos_note = f"Position (베지어 {simplified_count}개, 원본 {valid_count}개)"
    else:
        position_js      = build_position_js_array(frames, fps)
        pos_data_comment = "// ── 4. Position 키프레임 데이터 ─────────────────────────"
        pos_apply_block  = f"""\
    // ── 5. Position 키프레임 적용 ───────────────────────────
    var position = nullLayer.property("Position");
    for (var i = 0; i < keyframes.length; i++) {{
        var kf = keyframes[i];
        position.setValueAtTime(kf.time, [kf.x, kf.y]);
    }}
    for (var k = 1; k <= position.numKeys; k++) {{
        position.setInterpolationTypeAtKey(
            k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR
        );
    }}"""
        kf_count_display = valid_count
        pos_note         = "Position"

    # 헤더 주석용 적용 속성 목록
    props = [pos_note]
    if add_scale:
        props.append(f"Scale ({scale_range:.1f}% 변동)")
    if add_rotation:
        props.append(f"Rotation ({rot_range:.1f}° 변동)")
    prop_note = " + ".join(props)

    # Scale JSX 섹션 (조건부 삽입)
    if add_scale:
        scale_js = build_scale_js_array(frames, fps)
        n_scale = sum(1 for f in frames if f.get("scale") is not None)
        scale_block = f"""\

    // ── Scale 키프레임 데이터 ({scale_range:.1f}% 변동) ─────────────
    var scaleKeyframes = {scale_js};

    // ── Scale 키프레임 적용 ──────────────────────────────────
    var scaleProp = nullLayer.property("Scale");
    for (var j = 0; j < scaleKeyframes.length; j++) {{
        var skf = scaleKeyframes[j];
        scaleProp.setValueAtTime(skf.time, [skf.scale, skf.scale]);
    }}
    for (var m = 1; m <= scaleProp.numKeys; m++) {{
        scaleProp.setInterpolationTypeAtKey(
            m,
            KeyframeInterpolationType.LINEAR,
            KeyframeInterpolationType.LINEAR
        );
    }}
"""
        alert_scale_line = f'"Scale: {n_scale}개\\\\n" +'
    else:
        scale_block = ""
        alert_scale_line = '""+'

    # Rotation JSX 섹션 (조건부 삽입)
    if add_rotation:
        rotation_js = build_rotation_js_array(frames, fps)
        n_rotation = sum(1 for f in frames if f.get("rotation") is not None)
        rotation_block = f"""\

    // ── Rotation 키프레임 데이터 ({rot_range:.1f}° 변동) ────────────
    var rotationKeyframes = {rotation_js};

    // ── Rotation 키프레임 적용 ───────────────────────────────
    var rotProp = nullLayer.property("Rotation");
    for (var r = 0; r < rotationKeyframes.length; r++) {{
        var rkf = rotationKeyframes[r];
        rotProp.setValueAtTime(rkf.time, rkf.rotation);
    }}
    for (var rk = 1; rk <= rotProp.numKeys; rk++) {{
        rotProp.setInterpolationTypeAtKey(
            rk,
            KeyframeInterpolationType.LINEAR,
            KeyframeInterpolationType.LINEAR
        );
    }}
"""
        alert_rotation_line = f'"Rotation: {n_rotation}개\\\\n" +'
    else:
        rotation_block = ""
        alert_rotation_line = '""+'

    jsx = f"""\
// ============================================================
// 이 스크립트는 모션그래픽 추출기로 자동 생성됨
// 원본 영상: {video_name}
// 영상 해상도: {width}x{height}  /  FPS: {fps}
// 유효 키프레임: {valid_count}개  /  적용 속성: {prop_note}
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

    {pos_data_comment}
    var keyframes = {position_js};

    app.beginUndoGroup("모션 키프레임 적용: {layer_name}");

    {pos_apply_block}
{scale_block}{rotation_block}
    app.endUndoGroup();

    // ── 완료 알림 ────────────────────────────────────────────
    alert(
        "키프레임 적용 완료!\\n" +
        "레이어: {layer_name}\\n" +
        "Position: " + {kf_count_display} + "개\\n" +
        {alert_scale_line}
        {alert_rotation_line}
        "\\n※ 컴포지션 프레임 레이트가 {fps}fps인지 확인하세요."
    );
}})();
"""
    return jsx


def convert(json_path: Path, simplify: bool = False) -> None:
    """JSON 좌표 파일을 읽어 .jsx 파일로 변환한다."""
    jsx_path = json_path.with_name(json_path.stem.replace("_coords", "") + ".jsx")

    print(f"변환 시작: {json_path.name}")

    data   = load_coords(json_path)
    frames = data["frames"]
    total  = len(frames)
    valid  = sum(1 for f in frames if f["x"] is not None)

    if valid == 0:
        print("오류: 유효한 좌표 데이터가 없습니다. 추출 결과를 확인해주세요.")
        sys.exit(1)

    if valid < total:
        print(f"  경고: {total - valid}개 프레임은 좌표가 없어 키프레임에서 제외됩니다.")

    add_scale    = should_add_scale_keyframes(frames)
    add_rotation = should_add_rotation_keyframes(frames)
    scales       = [f["scale"]    for f in frames if f.get("scale")    is not None]
    rotations_l  = [f["rotation"] for f in frames if f.get("rotation") is not None]
    scale_range  = (max(scales)     - min(scales))     if scales     else 0.0
    rot_range    = (max(rotations_l) - min(rotations_l)) if rotations_l else 0.0

    # 베지어 단순화는 --simplify 옵션 사용 시에만
    simplify_result = simplify_motion_path(data) if simplify else None

    jsx_code = build_jsx_script(data, simplify_result=simplify_result)

    with open(jsx_path, "w", encoding="utf-8") as f:
        f.write(jsx_code)

    print(f"\n완료!")
    print(f"  출력 파일: {jsx_path}")
    if simplify and simplify_result:
        orig = simplify_result['original_count']
        simp = simplify_result['simplified_count']
        tol  = simplify_result['tolerance_px']
        print(f"  Position 키프레임: {orig}개 → {simp}개  "
              f"(RDP {tol}px, {orig - simp}개 제거)")
    else:
        print(f"  Position 키프레임: {valid}개 (전체 프레임)")
    if add_scale:
        n_scale = sum(1 for f in frames if f.get("scale") is not None)
        print(f"  Scale 키프레임:    {n_scale}개  (변동폭 {scale_range:.1f}%)")
    else:
        print(f"  Scale 키프레임:    생략  (변동폭 {scale_range:.1f}% < 5%)")
    if add_rotation:
        n_rot = sum(1 for f in frames if f.get("rotation") is not None)
        print(f"  Rotation 키프레임: {n_rot}개  (변동폭 {rot_range:.1f}°)")
    else:
        print(f"  Rotation 키프레임: 생략  (변동폭 {rot_range:.1f}° < 1°)")
    print(f"\nAE 사용법:")
    print(f"  File → Scripts → Run Script File → {jsx_path.name} 선택")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="JSON 좌표 → AE .jsx 변환기")
    parser.add_argument("json_path",     help="좌표 JSON 파일 경로")
    parser.add_argument("--simplify", action="store_true",
                        help="RDP 베지어 단순화 활성화 (기본: 전체 프레임 선형)")
    args = parser.parse_args()

    json_path = Path(args.json_path)
    if not json_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다 → {json_path}")
        sys.exit(1)

    convert(json_path, simplify=args.simplify)
