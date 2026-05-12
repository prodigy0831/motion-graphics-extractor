"""
AI 생성 PNG + 텍스트 좌표 JSON → AE PNG 레이어 임포트 통합 .jsx 생성기

output/<name>_text_coords.json 과 AI 생성 PNG 경로를 받아
PNG 자동 임포트 + 모션 키프레임 적용하는 AE ExtendScript를 생성한다.

사용법:
    venv_sam2/bin/python src/build_final_jsx.py \
        --json-path output/video_text_coords.json \
        --ai-png-path output/video_generated_text.png \
        --output-jsx output/video_final.jsx
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from text_json_to_jsx import (
    apply_dead_zone,
    pick_opacity_keyframes,
    _build_linear_pos_js,
    _build_scale_js,
    _build_opacity_js,
    SCALE_THRESHOLD,
)


def _js_escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def build_final_jsx(data: dict, ai_png_path: Path) -> str:
    """텍스트 JSON + AI PNG 경로로 AE 통합 .jsx를 생성한다."""
    vi     = data['video_info']
    frames = data['frames']
    fps    = float(vi['fps'])
    width  = int(vi['width'])
    height = int(vi['height'])

    frames      = apply_dead_zone(frames)
    valid_count = sum(1 for f in frames if f['x'] is not None and f['y'] is not None)
    pos_js      = _build_linear_pos_js(frames, fps)

    scale_vals = [f['scale'] for f in frames if f.get('scale') is not None]
    if scale_vals:
        scale_pcts = [v * 100 for v in scale_vals]
        add_scale  = (max(scale_pcts) - min(scale_pcts)) >= SCALE_THRESHOLD
    else:
        add_scale = False

    opacity_kfs = pick_opacity_keyframes(frames, fps)
    add_opacity = len(opacity_kfs) > 0

    if add_scale:
        scale_js    = _build_scale_js(frames, fps)
        scale_block = f"""\

    // ── Scale 키프레임 ────────────────────────────────────────
    var scaleKeyframes = {scale_js};

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

    if add_opacity:
        opacity_js    = _build_opacity_js(opacity_kfs)
        opacity_block = f"""\

    // ── Opacity 키프레임 (핵심 {len(opacity_kfs)}개) ──────────────────────
    var opacityKeyframes = {opacity_js};

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

    png_path_escaped = _js_escape(str(ai_png_path.resolve()))

    return f"""\
// ============================================================
// 이 스크립트는 모션그래픽 추출기 (AI 텍스트 통합 모드) 로 자동 생성됨
// 영상 해상도: {width}x{height}  /  FPS: {fps}
//
// 역할:
//   1. AI 생성 PNG 를 프로젝트에 자동 임포트
//   2. 컴포지션에 PNG 레이어 추가
//   3. Position 키프레임 {valid_count}개 (전체 프레임 선형 보간) 적용
//
// ⚠ PNG 경로가 이 Mac의 절대 경로로 박혀 있습니다.
//   다른 컴퓨터에서 실행하면 파일을 찾지 못합니다.
//   이동 후 실행 시 아래 pngPath 변수를 수정하세요.
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
            "Position 좌표는 원본 영상 기준으로 입력됩니다.\\n" +
            "컴포지션 해상도를 {width}x{height}로 맞추면 정확합니다."
        );
    }}

    // ── 3. AI PNG 존재 확인 ──────────────────────────────────
    var pngPath = "{png_path_escaped}";
    var pngFile = new File(pngPath);
    if (!pngFile.exists) {{
        alert(
            "AI PNG 파일을 찾을 수 없습니다:\\n" + pngPath +
            "\\n\\n이 스크립트는 이 Mac의 해당 경로에 PNG가 있을 때만 동작합니다.\\n" +
            "파일이 이동됐다면 스크립트의 pngPath 변수를 직접 수정하세요."
        );
        return;
    }}

    app.beginUndoGroup("AI 텍스트 PNG 모션 적용");

    // ── 4. PNG 임포트 + 레이어 추가 ─────────────────────────
    var importOpts = new ImportOptions(pngFile);
    var pngItem    = app.project.importFile(importOpts);
    var textLayer  = comp.layers.add(pngItem);
    textLayer.name = "AI 텍스트";

    // ── 5. Position 키프레임 데이터 ({valid_count}개, 전체 프레임) ───────────
    var keyframes = {pos_js};

    // ── 6. Position 키프레임 적용 (선형 보간) ────────────────
    // PNG 레이어는 2D → [x, y] 2원소 배열
    var position = textLayer.property("Position");
    for (var i = 0; i < keyframes.length; i++) {{
        var kf = keyframes[i];
        position.setValueAtTime(kf.time, [kf.x, kf.y]);
    }}
    for (var k = 1; k <= position.numKeys; k++) {{
        position.setInterpolationTypeAtKey(
            k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR
        );
    }}
{scale_block}{opacity_block}
    app.endUndoGroup();

    alert(
        "AI 텍스트 PNG 모션 적용 완료!\\n\\n" +
        "레이어명: AI 텍스트\\n" +
        "Position: " + keyframes.length + "개 키프레임 (선형)\\n\\n" +
        "※ 레이어 Scale을 조정해 텍스트 크기를 원하는 대로 맞춰보세요.\\n" +
        "※ 컴포지션 FPS가 {fps}fps인지 확인하세요."
    );
}})();
"""


def run(json_path: Path, ai_png_path: Path, output_jsx: Path) -> None:
    """통합 .jsx를 생성하고 경로를 stdout으로 출력한다."""
    output_jsx.parent.mkdir(parents=True, exist_ok=True)

    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    if data.get('object_type') != 'text':
        print("ERROR: 텍스트 모드 JSON이 아닙니다 (object_type != 'text')", flush=True)
        sys.exit(1)

    if not ai_png_path.exists():
        print(f"ERROR: AI PNG 파일을 찾을 수 없습니다: {ai_png_path}", flush=True)
        sys.exit(1)

    jsx_code = build_final_jsx(data, ai_png_path)

    with open(output_jsx, 'w', encoding='utf-8') as f:
        f.write(jsx_code)

    print(f"JSX_READY: {output_jsx}", flush=True)
    print(f"완료: {output_jsx.name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI PNG + 텍스트 JSON → 통합 AE .jsx 생성")
    parser.add_argument('--json-path',   required=True)
    parser.add_argument('--ai-png-path', required=True)
    parser.add_argument('--output-jsx',  required=True)
    args = parser.parse_args()

    try:
        run(Path(args.json_path), Path(args.ai_png_path), Path(args.output_jsx))
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        import traceback; traceback.print_exc()
        sys.exit(1)
