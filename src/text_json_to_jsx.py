"""
텍스트 추출 결과 JSON → After Effects .jsx 스크립트 변환기

output/<name>_text_coords.json 을 읽어 AE 텍스트 레이어 + 모션 키프레임을 생성한다.

- Position 키프레임: 전체 프레임 선형 보간 (dead zone 필터로 노이즈 제거)
- Scale 키프레임: 변동폭 5% 이상일 때 생성
- Opacity 키프레임: 페이드인/아웃 핵심 4점만 생성
- Rotation 키프레임: SAM 2 마스크 노이즈로 인한 튐 회피를 위해 생략

사용법:
    venv_sam2/bin/python src/text_json_to_jsx.py output/video_text_coords.json
"""

import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# 같은 src/ 폴더의 simplify_path 사용
sys.path.insert(0, str(Path(__file__).parent))
from simplify_path import simplify_motion_path

SCALE_THRESHOLD   = 5.0   # scale 변동폭 (%) 미만이면 Scale 키프레임 생략
OPACITY_THRESHOLD = 0.05  # opacity 변동폭 미만이면 Opacity 키프레임 생략

# Dead zone: SAM 2 마스크 노이즈로 인한 미세 흔들림 역치
DEAD_ZONE_PX    = 6.0   # 6픽셀 이내 위치 변화 → 이전 좌표로 스냅 (1280px 기준 0.47%)
DEAD_ZONE_SCALE = 0.05  # 5% 이내 스케일 변화 → 이전 값으로 스냅

# macOS 기본 설치 한글 산세리프 폰트
FONT_MAP = {
    "Bold":    "AppleSDGothicNeoB00",
    "Regular": "AppleSDGothicNeoR00",
    "Light":   "AppleSDGothicNeoL00",
}


def hex_to_ae_color(hex_str: str) -> Tuple[float, float, float]:
    """#RRGGBB 형태 hex를 AE [R, G, B] 0-1 범위로 변환한다."""
    h = hex_str.lstrip('#')
    if len(h) != 6:
        return (1.0, 1.0, 1.0)
    return (
        round(int(h[0:2], 16) / 255.0, 4),
        round(int(h[2:4], 16) / 255.0, 4),
        round(int(h[4:6], 16) / 255.0, 4),
    )


def pick_opacity_keyframes(frames: List[dict], fps: float) -> List[dict]:
    """opacity 변화의 핵심 키프레임을 추출한다.

    시작점 → 페이드인 시작 → 페이드인 완료 → 페이드아웃 시작 → 끝점 순서.
    변동폭 OPACITY_THRESHOLD 미만이면 빈 리스트 반환.
    """
    pairs = [
        (int(f['frame']), float(f.get('opacity') or 0.0))
        for f in frames
        if f.get('opacity') is not None
    ]
    if len(pairs) < 2:
        return []

    vals = [op for _, op in pairs]
    if max(vals) - min(vals) < OPACITY_THRESHOLD:
        return []

    key_set = set()

    # 항상 포함: 첫 프레임
    key_set.add(pairs[0][0])

    # opacity > 0 첫 지점 (페이드인 시작)
    for fi, op in pairs:
        if op > 0.0:
            key_set.add(fi)
            break

    # opacity >= 0.95 첫 지점 (페이드인 완료)
    for fi, op in pairs:
        if op >= 0.95:
            key_set.add(fi)
            break

    # 0.95 이상에서 처음 떨어지는 지점 (페이드아웃 시작)
    peaked = False
    for fi, op in pairs:
        if op >= 0.95:
            peaked = True
        elif peaked and op < 0.95:
            key_set.add(fi)
            break

    # 항상 포함: 마지막 프레임
    key_set.add(pairs[-1][0])

    op_map = {fi: op for fi, op in pairs}
    result = []
    for fi in sorted(key_set):
        if fi in op_map:
            result.append({
                'frame':       fi,
                'time':        round(fi / fps, 6),
                'opacity_pct': round(op_map[fi] * 100, 2),
            })
    return result


def apply_dead_zone(frames: List[dict]) -> List[dict]:
    """SAM 2 마스크 노이즈로 인한 미세 흔들림을 제거한다.

    직전 확정된 위치/스케일에서 DEAD_ZONE 이하로 변하면
    이전 값으로 스냅해 불필요한 키프레임 박힘을 막는다.
    진짜 움직임(역치 이상)은 그대로 통과.
    """
    import math
    result      = []
    prev_x      = prev_y = prev_s = None
    pos_total   = pos_snap = 0
    scale_total = scale_snap = 0

    for f in frames:
        nf = dict(f)

        # Position 필터
        if f['x'] is not None and f['y'] is not None:
            pos_total += 1
            if prev_x is None:
                prev_x, prev_y = float(f['x']), float(f['y'])
            else:
                dist = math.sqrt((f['x'] - prev_x) ** 2 + (f['y'] - prev_y) ** 2)
                if dist < DEAD_ZONE_PX:
                    nf['x'] = prev_x   # 이전 값으로 스냅
                    nf['y'] = prev_y
                    pos_snap += 1
                else:
                    prev_x, prev_y = float(f['x']), float(f['y'])

        # Scale 필터
        if f.get('scale') is not None:
            scale_total += 1
            if prev_s is None:
                prev_s = float(f['scale'])
            else:
                if abs(float(f['scale']) - prev_s) < DEAD_ZONE_SCALE:
                    nf['scale'] = prev_s  # 이전 값으로 스냅
                    scale_snap += 1
                else:
                    prev_s = float(f['scale'])

        result.append(nf)

    print(
        f"Dead zone 적용: "
        f"Position {pos_total}개 → 변화 {pos_total - pos_snap}개, 스냅 {pos_snap}개  |  "
        f"Scale {scale_total}개 → 변화 {scale_total - scale_snap}개, 스냅 {scale_snap}개  "
        f"(역치: {DEAD_ZONE_PX}px / {int(DEAD_ZONE_SCALE * 100)}%)",
        flush=True,
    )
    return result


def _build_linear_pos_js(frames: List[dict], fps: float) -> str:
    """전체 프레임의 Position 데이터를 JS 배열 리터럴로 변환한다 (선형 보간용)."""
    lines = []
    for f in frames:
        if f['x'] is None or f['y'] is None:
            continue
        lines.append(
            f"  {{frame:{f['frame']}, time:{round(f['frame']/fps,6):.6f}, "
            f"x:{f['x']}, y:{f['y']}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def _build_scale_js(frames: List[dict], fps: float) -> str:
    """Scale 키프레임 배열을 JS 리터럴로 변환한다.

    text JSON의 scale은 비율(1.0=기준), AE Scale은 퍼센트이므로 ×100.
    """
    lines = []
    for f in frames:
        if f.get('scale') is None:
            continue
        scale_pct = round(float(f['scale']) * 100.0, 2)
        lines.append(
            f"  {{frame:{f['frame']}, time:{round(f['frame']/fps,6):.6f}, "
            f"scale:{scale_pct}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def _build_opacity_js(keyframes: List[dict]) -> str:
    """Opacity 키프레임 배열을 JS 리터럴로 변환한다."""
    lines = []
    for kf in keyframes:
        lines.append(
            f"  {{frame:{kf['frame']}, time:{kf['time']:.6f}, "
            f"opacity_pct:{kf['opacity_pct']}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n]"


def _js_escape(s: str) -> str:
    """JS 문자열 리터럴 안에 넣을 수 있게 이스케이프한다."""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def build_jsx_script(data: dict, stem: str) -> str:
    """텍스트 추출 JSON으로부터 AE ExtendScript 전체를 생성한다."""
    vi     = data['video_info']
    meta   = data.get('text_metadata', {})
    frames = data['frames']
    fps    = float(vi['fps'])
    width  = int(vi['width'])
    height = int(vi['height'])

    content   = _js_escape(meta.get('content', '') or '')
    font_name = FONT_MAP.get(meta.get('weight', 'Regular'), FONT_MAP['Regular'])
    size_px   = int(meta.get('size_px', 60) or 60)
    color_hex = meta.get('color', '#FFFFFF') or '#FFFFFF'
    r, g, b   = hex_to_ae_color(color_hex)
    layer_name = f"Text_{stem}"

    # ── Dead zone 필터 (마스크 노이즈 제거) ─────────────────────
    frames = apply_dead_zone(frames)

    # ── Position (전체 프레임 선형) ─────────────────────────────
    valid_count = sum(1 for f in frames if f['x'] is not None and f['y'] is not None)
    pos_js      = _build_linear_pos_js(frames, fps)

    # ── Scale ───────────────────────────────────────────────────
    scale_vals = [f['scale'] for f in frames if f.get('scale') is not None]
    if scale_vals:
        # text scale은 비율, 퍼센트로 변환 후 변동폭 계산
        scale_pcts = [v * 100 for v in scale_vals]
        add_scale  = (max(scale_pcts) - min(scale_pcts)) >= SCALE_THRESHOLD
    else:
        add_scale = False

    # ── Opacity ─────────────────────────────────────────────────
    opacity_kfs = pick_opacity_keyframes(frames, fps)
    add_opacity = len(opacity_kfs) > 0

    # ── 적용 속성 목록 (헤더 주석용) ────────────────────────────
    props = [f"Position ({valid_count}개, 전체 프레임 선형)"]
    if add_scale:
        props.append("Scale")
    if add_opacity:
        props.append("Opacity")
    props.append("Rotation 생략 (노이즈 회피)")

    # ── Scale JS 블록 ───────────────────────────────────────────
    if add_scale:
        scale_js = _build_scale_js(frames, fps)
        scale_block = f"""\

    // ── Scale 키프레임 데이터 ─────────────────────────────────
    var scaleKeyframes = {scale_js};

    // ── Scale 키프레임 적용 ──────────────────────────────────
    var scaleProp = textLayer.property("Scale");
    for (var j = 0; j < scaleKeyframes.length; j++) {{
        var skf = scaleKeyframes[j];
        scaleProp.setValueAtTime(skf.time, [skf.scale, skf.scale]);
    }}
    for (var m = 1; m <= scaleProp.numKeys; m++) {{
        scaleProp.setInterpolationTypeAtKey(
            m, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR
        );
    }}
"""
    else:
        scale_block = ""

    # ── Opacity JS 블록 ─────────────────────────────────────────
    if add_opacity:
        opacity_js = _build_opacity_js(opacity_kfs)
        opacity_block = f"""\

    // ── Opacity 키프레임 데이터 (핵심 {len(opacity_kfs)}개) ───────────────
    var opacityKeyframes = {opacity_js};

    // ── Opacity 키프레임 적용 ────────────────────────────────
    var opacProp = textLayer.property("Opacity");
    for (var op = 0; op < opacityKeyframes.length; op++) {{
        var okf = opacityKeyframes[op];
        opacProp.setValueAtTime(okf.time, okf.opacity_pct);
    }}
    for (var ok = 1; ok <= opacProp.numKeys; ok++) {{
        opacProp.setInterpolationTypeAtKey(
            ok, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR
        );
    }}
"""
    else:
        opacity_block = ""

    jsx = f"""\
// ============================================================
// 이 스크립트는 모션그래픽 추출기 (텍스트 모드) 로 자동 생성됨
// 영상 해상도: {width}x{height}  /  FPS: {fps}
// 추출된 텍스트: "{content}"
// 적용 속성: {" + ".join(props)}
//
// 텍스트 흔들림 방지: {DEAD_ZONE_PX}px 이하 위치 변화, {int(DEAD_ZONE_SCALE*100)}% 이하 스케일 변화는 노이즈로 간주하여 무시됨
// 폰트는 시스템 한글 산세리프로 기본 설정됨
// AE에서 텍스트 레이어 선택 후 폰트 패널에서 변경 가능
//
// 회전 키프레임은 노이즈 회피를 위해 의도적으로 생략됨
// 텍스트 회전이 필요한 경우 AE에서 직접 키프레임 추가
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
            "좌표가 정확하려면 컴포지션 해상도를 {width}x{height}로 맞춰주세요."
        );
    }}

    // ── 3. 텍스트 레이어 생성 ────────────────────────────────
    var textContent = "{content}";
    var textLayer   = comp.layers.addText(textContent);
    textLayer.name  = "{layer_name}";

    // ── 4. 텍스트 스타일 설정 ────────────────────────────────
    var textProp = textLayer.property("Source Text");
    var td       = textProp.value;
    td.font        = "{font_name}";
    td.fontSize    = {size_px};
    td.fillColor   = [{r:.4f}, {g:.4f}, {b:.4f}];
    td.applyFill   = true;
    td.applyStroke = false;
    textProp.setValue(td);

    // ── 5. Position 키프레임 데이터 ({valid_count}개, 전체 프레임) ───────────────
    var keyframes = {pos_js};

    app.beginUndoGroup("텍스트 모션 적용: {layer_name}");

    // ── 6. Position 키프레임 적용 (선형 보간) ────────────────
    // 텍스트 레이어는 Position을 3D [x, y, z] 로 관리 → z=0 추가
    var position = textLayer.property("Position");
    for (var i = 0; i < keyframes.length; i++) {{
        var kf = keyframes[i];
        position.setValueAtTime(kf.time, [kf.x, kf.y, 0]);
    }}
    for (var k = 1; k <= position.numKeys; k++) {{
        position.setInterpolationTypeAtKey(
            k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR
        );
    }}
{scale_block}{opacity_block}
    app.endUndoGroup();

    // ── 완료 알림 ────────────────────────────────────────────
    alert(
        "텍스트 모션 적용 완료!\\n" +
        "레이어: {layer_name}\\n" +
        "Position: " + keyframes.length + "개 (선형)\\n" +
        "\\n※ 앵커 포인트를 중앙으로 조정하면 위치가 더 정확해집니다.\\n" +
        "\\n※ 컴포지션 프레임 레이트가 {fps}fps인지 확인하세요."
    );
}})();
"""
    return jsx


def convert(json_path: Path) -> None:
    """텍스트 JSON 파일을 읽어 _text.jsx 파일로 변환한다."""
    jsx_path = json_path.with_name(json_path.stem.replace('_text_coords', '') + '_text.jsx')

    print(f"변환 시작: {json_path.name}")

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    if data.get('object_type') != 'text':
        print("오류: 텍스트 모드 JSON이 아닙니다. (object_type != 'text')")
        sys.exit(1)

    stem = json_path.stem.replace('_text_coords', '')

    frames     = data['frames']
    total      = len(frames)
    visible    = sum(1 for f in frames if f['x'] is not None)
    fps        = float(data['video_info']['fps'])

    if visible == 0:
        print("오류: 유효한 좌표 데이터가 없습니다.")
        sys.exit(1)

    meta   = data.get('text_metadata', {})
    op_kfs = pick_opacity_keyframes(frames, fps)

    jsx_code = build_jsx_script(data, stem)

    with open(jsx_path, 'w', encoding='utf-8') as f:
        f.write(jsx_code)

    flat  = {'fps': fps, 'width': data['video_info']['width'],
             'height': data['video_info']['height'], 'frames': frames}
    simp  = simplify_motion_path(flat)

    scale_vals = [f['scale'] for f in frames if f.get('scale') is not None]
    add_scale  = bool(scale_vals) and (
        (max(v * 100 for v in scale_vals) - min(v * 100 for v in scale_vals)) >= SCALE_THRESHOLD
    )

    print(f"\n완료!")
    print(f"  출력 파일: {jsx_path}")
    print(f"  인식 텍스트: '{meta.get('content', '')}'")
    print(f"  폰트: {FONT_MAP.get(meta.get('weight','Regular'), FONT_MAP['Regular'])}")
    print(f"  Position 키프레임: {simp['original_count']}개 → {simp['simplified_count']}개")
    if add_scale:
        print(f"  Scale 키프레임:    {visible}개")
    else:
        print(f"  Scale 키프레임:    생략 (변동폭 < {SCALE_THRESHOLD}%)")
    if op_kfs:
        print(f"  Opacity 키프레임: {len(op_kfs)}개 (핵심 지점)")
    else:
        print(f"  Opacity 키프레임: 생략 (변동폭 < {int(OPACITY_THRESHOLD*100)}%)")
    print(f"\nAE 사용법:")
    print(f"  File → Scripts → Run Script File → {jsx_path.name} 선택")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python src/text_json_to_jsx.py output/<name>_text_coords.json")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    if not json_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다 → {json_path}")
        sys.exit(1)

    convert(json_path)
