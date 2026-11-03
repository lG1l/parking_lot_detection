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
    // 고른 차량은 노랑, 파손 부위는 주황, 바닥 변은 흰색, 고른 파손 변은 빨강 (D-190)
    for (final d in o.detections) {
      if (d.detId == o.hoveredDetId) _fill(canvas, d.polygon, _lightAlpha);
    }
    final selected = o.selectedPolygon;
    if (selected != null) _fill(canvas, selected, o.selectedStrong ? _strongAlpha : _lightAlpha);
    final damage = o.damageBox;
    if (damage != null) {
      final r = _rect(damage);
      canvas.drawRect(r, Paint()..color = damageColor.withValues(alpha: 0.15));
      canvas.drawRect(
        r,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 3
          ..color = damageColor,
      );
    }
    if (o.corners.length == 4) {
      for (var i = 0; i < 4; i++) {
        final chosen = o.edges.contains(i);
        canvas.drawLine(
          _off(o.corners[i]),
          _off(o.corners[(i + 1) % 4]),
          Paint()
            ..strokeWidth = chosen ? 7 : (o.edgesClickable ? 4 : 2)
            ..color = chosen ? chosenEdgeColor : floorEdgeColor,
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
    for (var i = 0; i < o.corners.length; i++) {
      final c = _off(o.corners[i]);
      canvas.drawCircle(c, 8, Paint()..color = inkColor);
      final tp = TextPainter(
        text: TextSpan(
          text: '${i + 1}',
          style: const TextStyle(color: offWhiteColor, fontSize: 9, fontWeight: FontWeight.bold),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, c - Offset(tp.width / 2, tp.height / 2));
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
