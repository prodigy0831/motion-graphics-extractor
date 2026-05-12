"""
모션 패스 단순화: Ramer-Douglas-Peucker + Catmull-Rom 베지어 핸들

사용 예:
    from simplify_path import simplify_motion_path
    result = simplify_motion_path(data, tolerance_ratio=0.005)
"""

import math
from typing import List, Tuple, Dict


def ramer_douglas_peucker(
    points: List[Tuple[float, float, int]],
    tolerance: float,
) -> List[Tuple[float, float, int]]:
    """RDP 알고리즘으로 (x, y, frame) 점 목록 단순화.

    시작점·끝점을 유지하면서 직선에서 tolerance 픽셀 미만으로 벗어난
    중간 점들을 재귀적으로 제거한다.
    """
    if len(points) <= 2:
        return list(points)

    sx, sy = points[0][0], points[0][1]
    ex, ey = points[-1][0], points[-1][1]
    line_len = math.hypot(ex - sx, ey - sy)

    max_dist = 0.0
    max_idx  = 0
    for i in range(1, len(points) - 1):
        px, py = points[i][0], points[i][1]
        if line_len == 0:
            dist = math.hypot(px - sx, py - sy)
        else:
            dist = abs((ey - sy) * px - (ex - sx) * py + ex * sy - ey * sx) / line_len
        if dist > max_dist:
            max_dist, max_idx = dist, i

    if max_dist > tolerance:
        left  = ramer_douglas_peucker(points[:max_idx + 1], tolerance)
        right = ramer_douglas_peucker(points[max_idx:],     tolerance)
        return left[:-1] + right
    return [points[0], points[-1]]


def fit_bezier_handles(points: List[Dict]) -> List[Dict]:
    """Catmull-Rom → Cubic Bezier 변환으로 AE 공간 접선 핸들 계산.

    points: [{'frame': int, 'time': float, 'x': float, 'y': float}, ...]
    Returns: 동일 형태 + in_x, in_y, out_x, out_y 필드 추가

    AE setSpatialTangentsAtKey의 핸들은 키프레임 위치 기준 상대 좌표.
    - out_tangent: 다음 키프레임 방향 (양수)
    - in_tangent:  이전 키프레임 방향 (음수, 반대 방향)
    """
    n = len(points)
    result = []

    for i, pt in enumerate(points):
        px, py = float(pt['x']), float(pt['y'])

        if n == 1:
            result.append({**pt, 'in_x': 0.0, 'in_y': 0.0,
                                  'out_x': 0.0, 'out_y': 0.0})
        elif i == 0:
            # 첫 점: out 핸들만 (다음 점까지 거리의 1/3)
            ox = (float(points[1]['x']) - px) / 3.0
            oy = (float(points[1]['y']) - py) / 3.0
            result.append({**pt, 'in_x': 0.0, 'in_y': 0.0,
                                  'out_x': ox,  'out_y': oy})
        elif i == n - 1:
            # 마지막 점: in 핸들만 (이전 점 반대 방향으로 1/3)
            ix = (float(points[i-1]['x']) - px) / 3.0
            iy = (float(points[i-1]['y']) - py) / 3.0
            result.append({**pt, 'in_x': ix,  'in_y': iy,
                                  'out_x': 0.0, 'out_y': 0.0})
        else:
            # 중간 점: Catmull-Rom 접선 → Bezier 핸들 (이전↔다음 차이의 1/6)
            tx = (float(points[i+1]['x']) - float(points[i-1]['x'])) / 6.0
            ty = (float(points[i+1]['y']) - float(points[i-1]['y'])) / 6.0
            result.append({**pt, 'in_x': -tx, 'in_y': -ty,
                                  'out_x':  tx, 'out_y':  ty})

    return result


def simplify_motion_path(
    data: Dict,
    tolerance_ratio: float = 0.005,
    no_simplify: bool = False,
) -> Dict:
    """JSON 좌표 데이터에서 Position 모션 패스를 단순화한다.

    data: extract_with_sam2 / extract_coords 출력 dict
    tolerance_ratio: 영상 너비 대비 허용 오차 비율 (기본 0.5% ≈ 1280px 기준 6.4px)
    no_simplify: True면 원본 점 그대로 반환 (베지어 핸들만 추가)

    Returns: {
        'keyframes':        [{frame, time, x, y, in_x, in_y, out_x, out_y}, ...],
        'original_count':   int,
        'simplified_count': int,
        'tolerance_px':     float,
    }
    """
    frames = data.get('frames', [])
    fps    = float(data.get('fps', 30.0))
    vid_w  = float(data.get('width', 1280))

    valid = [
        (float(f['x']), float(f['y']), int(f['frame']))
        for f in frames
        if f['x'] is not None and f['y'] is not None
    ]
    original_count = len(valid)
    tolerance_px   = round(vid_w * tolerance_ratio, 2)

    if not valid:
        return {'keyframes': [], 'original_count': 0,
                'simplified_count': 0, 'tolerance_px': tolerance_px}

    if no_simplify or len(valid) <= 2:
        simplified = valid
    else:
        simplified = ramer_douglas_peucker(valid, tolerance_px)

    pts = [{'frame': p[2], 'time': round(p[2] / fps, 6),
            'x': p[0], 'y': p[1]} for p in simplified]
    keyframes = fit_bezier_handles(pts)

    return {
        'keyframes':        keyframes,
        'original_count':   original_count,
        'simplified_count': len(keyframes),
        'tolerance_px':     tolerance_px,
    }
