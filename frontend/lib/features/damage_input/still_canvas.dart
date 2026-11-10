import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../../app/theme.dart';
import '../../core/models/analysis.dart';
import 'geometry.dart';

/// 정지 장면 위에 그릴 것. 좌표는 모두 원본 픽셀이다.
/// [detections]는 마우스를 올린 차를 칠하는 데만 쓴다. 평소에는 차량 표시를 하지 않는다 (D-221).
class StillOverlay {
  const StillOverlay({
    this.detections = const [],
    this.hoveredDetId,
    this.selectedPolygon,
    this.selectedStrong = false,
    this.damageBox,
    this.damageCornersOnly = false,
    this.corners = const [],
    this.frontEdge,
    this.edges = const [],
    this.edgesClickable = false,
  });

  final List<Detection> detections;
  final int? hoveredDetId;
  final List<Pt>? selectedPolygon;

  /// 고르는 단계(①)에서는 진하게, 뒤 단계에서는 옅게 칠한다 (D-221, D-222).
  final bool selectedStrong;
  final Box? damageBox;

  /// 파손 부위를 그리는 단계(③)에서는 사각형 대신 빨간 네 모서리만 그린다 (캔버스, D-237).
  final bool damageCornersOnly;
  final List<Pt> corners;
  final int? frontEdge;
  final List<int> edges;
  final bool edgesClickable;
}

/// 원본 크기 [natural]의 이미지를 주어진 폭 안에 비율을 지켜 보여주고, 입력을 원본 좌표로 넘긴다.
/// 표시 영역을 이미지 크기에 딱 맞추므로 여백이 없고, 화면 좌표 ÷ 배율 = 원본 좌표다 (05장 5.6·5.7).
class StillCanvas extends StatefulWidget {
  const StillCanvas({
    super.key,
    required this.imageUrl,
    required this.natural,
    required this.overlay,
    this.onTap,
    this.onHover,
    this.onDragStart,
    this.onDragUpdate,
    this.onDragEnd,
    this.onEdgeTap,
    this.onImageError,
    this.maxHeight = 560,
  });

  final String imageUrl;
  final Size natural;
  final StillOverlay overlay;
  final void Function(double x, double y)? onTap;
  final void Function(double x, double y)? onHover;
  final void Function(Pt p)? onDragStart;
  final void Function(Pt p)? onDragUpdate;
  final VoidCallback? onDragEnd;
  final void Function(int edge)? onEdgeTap;
  final VoidCallback? onImageError;
  final double maxHeight;

  @override
  State<StillCanvas> createState() => _StillCanvasState();
}

class _StillCanvasState extends State<StillCanvas> {
  static const _edgeHitPx = 10.0;

  int get _w => widget.natural.width.round();
  int get _h => widget.natural.height.round();

  Pt _pt(Offset local, double scale) => toImagePoint(local.dx, local.dy, scale, _w, _h);

  void _tap(Offset local, double scale) {
    final o = widget.overlay;
    if (o.edgesClickable && o.corners.length == 4 && widget.onEdgeTap != null) {
      var best = -1;
      var bestDist = _edgeHitPx;
      for (var i = 0; i < 4; i++) {
        final a = o.corners[i];
        final b = o.corners[(i + 1) % 4];
        final d = distanceToSegment(local.dx, local.dy, a.x * scale, a.y * scale, b.x * scale, b.y * scale);
        if (d <= bestDist) {
          best = i;
          bestDist = d;
        }
      }
      if (best >= 0) widget.onEdgeTap!(best);
      return;
    }
    widget.onTap?.call(local.dx / scale, local.dy / scale);
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final scale = math.min(constraints.maxWidth / widget.natural.width, widget.maxHeight / widget.natural.height);
        final size = Size(widget.natural.width * scale, widget.natural.height * scale);
        final dragging = widget.onDragStart != null;
        return Center(
          child: SizedBox.fromSize(
            size: size,
            child: MouseRegion(
              cursor: dragging ? SystemMouseCursors.precise : SystemMouseCursors.click,
              onHover: (e) => widget.onHover?.call(e.localPosition.dx / scale, e.localPosition.dy / scale),
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                // 트랙패드 두 손가락 스크롤은 받지 않고 페이지 스크롤로 넘긴다
                supportedDevices: const {
                  PointerDeviceKind.mouse,
                  PointerDeviceKind.touch,
                  PointerDeviceKind.stylus,
                  PointerDeviceKind.invertedStylus,
                },
                onTapUp: (e) => _tap(e.localPosition, scale),
                onPanStart: dragging ? (e) => widget.onDragStart!(_pt(e.localPosition, scale)) : null,
                onPanUpdate: dragging ? (e) => widget.onDragUpdate?.call(_pt(e.localPosition, scale)) : null,
                onPanEnd: dragging ? (_) => widget.onDragEnd?.call() : null,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Image.network(
                      widget.imageUrl,
                      fit: BoxFit.fill,
                      webHtmlElementStrategy: WebHtmlElementStrategy.prefer,
                      errorBuilder: (context, error, stack) {
                        WidgetsBinding.instance.addPostFrameCallback((_) => widget.onImageError?.call());
                        return const ColoredBox(color: Colors.black12);
                      },
                    ),
                    IgnorePointer(child: CustomPaint(painter: _OverlayPainter(widget.overlay, scale))),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _OverlayPainter extends CustomPainter {
  _OverlayPainter(this.o, this.scale);

  final StillOverlay o;
  final double scale;

  static const _lightAlpha = 0.25;
  static const _strongAlpha = 0.6;

  void _fill(Canvas canvas, List<Pt> polygon, double alpha) {
    final path = Path()..addPolygon(polygon.map(_off).toList(), true);
    canvas.drawPath(path, Paint()..color = vehicleColor.withValues(alpha: alpha));
  }

  Rect _rect(Box b) => Rect.fromLTRB(b[0] * scale, b[1] * scale, b[2] * scale, b[3] * scale);
  Offset _off(Pt p) => Offset(p.x * scale, p.y * scale);

  @override
  void paint(Canvas canvas, Size size) {
    // 사각형과 윤곽선은 그리지 않는다. 마우스를 올린 차는 옅게, 고른 차는 ①에서 진하게, 뒤 단계에서 옅게 칠한다 (D-221, D-222).
    // 고른 차량은 노랑, 파손 부위는 주황(그리는 단계는 빨간 네 모서리), 바닥 변은 파랑, 고른 파손 변은 빨강 (D-190, D-237)
    for (final d in o.detections) {
      if (d.detId == o.hoveredDetId) _fill(canvas, d.polygon, _lightAlpha);
    }
    final selected = o.selectedPolygon;
    if (selected != null) _fill(canvas, selected, o.selectedStrong ? _strongAlpha : _lightAlpha);
    final damage = o.damageBox;
    if (damage != null) {
      final r = _rect(damage);
      if (o.damageCornersOnly) {
        _cornerMarks(canvas, r);
      } else {
        canvas.drawRect(r, Paint()..color = damageColor.withValues(alpha: 0.15));
        canvas.drawRect(
          r,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 3
            ..color = damageColor,
        );
      }
    }
    // 바닥 변: 찍은 점을 차례로 잇고, 네 점이면 닫는다. 파랑 선 아래에 옅은 빛 번짐을 깐다 (캔버스, D-237)
    final n = o.corners.length;
    for (var i = 0; i < (n == 4 ? 4 : n - 1); i++) {
      final a = _off(o.corners[i]);
      final b = _off(o.corners[(i + 1) % n]);
      canvas.drawLine(
        a,
        b,
        Paint()
          ..strokeWidth = 10
          ..strokeCap = StrokeCap.round
          ..color = cornerColor.withValues(alpha: _glowAlpha),
      );
      canvas.drawLine(
        a,
        b,
        Paint()
          ..strokeWidth = o.edgesClickable ? 4 : 3
          ..strokeCap = StrokeCap.round
          ..color = cornerColor,
      );
    }
    if (n == 4) {
      for (final i in o.edges) {
        canvas.drawLine(
          _off(o.corners[i]),
          _off(o.corners[(i + 1) % 4]),
          Paint()
            ..strokeWidth = 7
            ..color = chosenEdgeColor,
        );
      }
      // 앞쪽 변은 파랑. 파손 변과 같은 변이면 빨강 위에 점선으로 겹쳐 둘 다 보이게 한다 (D-212)
      final front = o.frontEdge;
      if (front != null) {
        final a = _off(o.corners[front]);
        final b = _off(o.corners[(front + 1) % 4]);
        final paint = Paint()
          ..strokeWidth = 7
          ..color = frontEdgeColor;
        if (o.edges.contains(front)) {
          _dashedLine(canvas, a, b, paint);
        } else {
          canvas.drawLine(a, b, paint);
        }
      }
    }
    // 찍은 점은 번호 없이 점만 그린다 (D-232). 파랑 점에 흰 테두리, 둘레에 옅은 빛 번짐 (캔버스, D-237)
    for (final corner in o.corners) {
      final c = _off(corner);
      canvas.drawCircle(c, 16, Paint()..color = cornerColor.withValues(alpha: _glowAlpha));
      canvas.drawCircle(c, 8, Paint()..color = cornerColor);
      canvas.drawCircle(
        c,
        8,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = floorEdgeColor,
      );
    }
  }

  static const _glowAlpha = 0.25;

  /// 사각형의 네 모서리에 ㄱ자 표시만 그린다. 팔 길이는 10px, 작은 사각형이면 변의 1/3까지 줄인다.
  void _cornerMarks(Canvas canvas, Rect r) {
    final arm = math.min(10.0, math.min(r.width, r.height) / 3);
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.square
      ..color = damageDragColor;
    for (final (corner, dx, dy) in [
      (r.topLeft, 1.0, 1.0),
      (r.topRight, -1.0, 1.0),
      (r.bottomLeft, 1.0, -1.0),
      (r.bottomRight, -1.0, -1.0),
    ]) {
      canvas.drawPath(
        Path()
          ..moveTo(corner.dx, corner.dy + dy * arm)
          ..lineTo(corner.dx, corner.dy)
          ..lineTo(corner.dx + dx * arm, corner.dy),
        paint,
      );
    }
  }

  void _dashedLine(Canvas canvas, Offset a, Offset b, Paint paint) {
    const dash = 10.0;
    final length = (b - a).distance;
    if (length == 0) return;
    final step = (b - a) / length;
    for (var t = 0.0; t < length; t += dash * 2) {
      canvas.drawLine(a + step * t, a + step * math.min(t + dash, length), paint);
    }
  }

  @override
  bool shouldRepaint(_OverlayPainter old) => true;
}
