import 'dart:math' as math;

import '../../core/models/analysis.dart';

/// 원본 해상도 기준 픽셀 점 (05장 5.7).
typedef Pt = ({int x, int y});

/// 화면 좌표(표시 배율 [scale])를 원본 픽셀 정수로 되돌린다. 이미지 밖은 가장자리로 붙인다.
Pt toImagePoint(double dx, double dy, double scale, int width, int height) => (
  x: (dx / scale).round().clamp(0, width),
  y: (dy / scale).round().clamp(0, height),
);

bool boxContainsPoint(Box b, double x, double y) =>
    x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];

/// [inner]가 [outer] 안(경계 포함)에 있는지 (05장 5.7 검증 7).
bool boxInside(Box inner, Box outer) =>
    inner[0] >= outer[0] && inner[1] >= outer[1] && inner[2] <= outer[2] && inner[3] <= outer[3];

int _area(Box b) => (b[2] - b[0]) * (b[3] - b[1]);

/// 누른 점을 품는 차량 중 고를 것 (07장 2.6 "겹친 사각형").
/// 넓이가 가장 작은 것을 잡고, 이미 고른 것을 다시 누르면 그다음으로 작은 것으로 바꾼다.
int? pickDetection(List<Detection> detections, double x, double y, int? current) {
  final hits = detections.where((d) => boxContainsPoint(d.bbox, x, y)).toList()
    ..sort((a, b) => _area(a.bbox).compareTo(_area(b.bbox)));
  if (hits.isEmpty) return null;
  final i = hits.indexWhere((d) => d.detId == current);
  return hits[(i + 1) % hits.length].detId;
}

/// 드래그 두 점으로 만든 사각형 [x1, y1, x2, y2]. 넓이가 0이면 null.
Box? boxFromDrag(Pt a, Pt b) {
  final box = [
    math.min(a.x, b.x),
    math.min(a.y, b.y),
    math.max(a.x, b.x),
    math.max(a.y, b.y),
  ];
  return box[0] < box[2] && box[1] < box[3] ? box : null;
}

int _orient(Pt a, Pt b, Pt c) {
  final v = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  return v.sign;
}

bool _onSegment(Pt a, Pt b, Pt p) =>
    math.min(a.x, b.x) <= p.x &&
    p.x <= math.max(a.x, b.x) &&
    math.min(a.y, b.y) <= p.y &&
    p.y <= math.max(a.y, b.y);

/// 두 선분이 만나는지 (끝점이 닿는 것 포함).
bool segmentsIntersect(Pt p1, Pt p2, Pt p3, Pt p4) {
  final d1 = _orient(p3, p4, p1);
  final d2 = _orient(p3, p4, p2);
  final d3 = _orient(p1, p2, p3);
  final d4 = _orient(p1, p2, p4);
  if (d1 != d2 && d3 != d4 && d1 != 0 && d2 != 0 && d3 != 0 && d4 != 0) return true;
  if (d1 == 0 && _onSegment(p3, p4, p1)) return true;
  if (d2 == 0 && _onSegment(p3, p4, p2)) return true;
  if (d3 == 0 && _onSegment(p1, p2, p3)) return true;
  if (d4 == 0 && _onSegment(p1, p2, p4)) return true;
  return false;
}

/// 찍은 순서대로 이은 네 모서리의 마주 보는 변(0과 2, 1과 3)이 만나면 꼬인 사각형 (05장 5.7 검증 12).
bool isTwisted(List<Pt> c) =>
    segmentsIntersect(c[0], c[1], c[2], c[3]) || segmentsIntersect(c[1], c[2], c[3], c[0]);

/// 파손 변 고르기 (05장 5.7 검증 13). 1개 또는 이웃한 2개만.
/// 돌려주는 값: 새 선택과, 마주 보는 변이라 막았는지.
({List<int> edges, bool blocked}) toggleEdge(List<int> current, int edge) {
  if (current.contains(edge)) {
    return (edges: current.where((e) => e != edge).toList(), blocked: false);
  }
  if (current.isEmpty) return (edges: [edge], blocked: false);
  if (current.length == 1) {
    final diff = (current.first - edge).abs();
    if (diff == 2) return (edges: current, blocked: true);
    return (edges: [current.first, edge]..sort(), blocked: false);
  }
  // 이미 2개면 새로 누른 변을 남은 하나와 짝지을 수 있을 때만 바꾼다
  final keep = current.firstWhere((e) => (e - edge).abs() != 2, orElse: () => -1);
  if (keep < 0) return (edges: current, blocked: true);
  return (edges: [keep, edge]..sort(), blocked: false);
}

/// 점과 선분 사이 거리 (변 누르기 판정용, 화면 좌표).
double distanceToSegment(double px, double py, double ax, double ay, double bx, double by) {
  final dx = bx - ax;
  final dy = by - ay;
  final len2 = dx * dx + dy * dy;
  final t = len2 == 0 ? 0.0 : (((px - ax) * dx + (py - ay) * dy) / len2).clamp(0.0, 1.0);
  final cx = ax + t * dx;
  final cy = ay + t * dy;
  return math.sqrt((px - cx) * (px - cx) + (py - cy) * (py - cy));
}
