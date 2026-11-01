import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../../app/theme.dart';
import '../../core/models/analysis.dart';
import 'geometry.dart';

/// 정지 장면 위에 그릴 것. 좌표는 모두 원본 픽셀이다.
class StillOverlay {
  const StillOverlay({
    this.detections = const [],
    this.hoveredDetId,
    this.selectedBox,
    this.damageBox,
    this.corners = const [],
    this.edges = const [],
    this.edgesClickable = false,
  });

  final List<Detection> detections;
  final int? hoveredDetId;
  final Box? selectedBox;
  final Box? damageBox;
  final List<Pt> corners;
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

  Rect _rect(Box b) => Rect.fromLTRB(b[0] * scale, b[1] * scale, b[2] * scale, b[3] * scale);
  Offset _off(Pt p) => Offset(p.x * scale, p.y * scale);

  @override
  void paint(Canvas canvas, Size size) {
    // 고르기 전 사각형은 얇은 선(2px)만, 마우스를 올린 것만 굵게 (07장 2.6)
    for (final d in o.detections) {
      final hovered = d.detId == o.hoveredDetId;
      canvas.drawRect(
        _rect(d.bbox),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = hovered ? 4 : 2
          ..color = hovered ? Colors.white : Colors.white70,
      );
    }
    final selected = o.selectedBox;
    if (selected != null) {
      // 고른 차량은 노랑, 파손 부위는 주황, 바닥 변은 흰색, 고른 파손 변은 빨강 (D-190)
      canvas.drawRect(_rect(selected), Paint()..color = vehicleColor.withValues(alpha: 0.12));
      canvas.drawRect(
        _rect(selected),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 4
          ..color = vehicleColor,
      );
    }
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
    }
    for (var i = 0; i < o.corners.length; i++) {
      final c = _off(o.corners[i]);
      canvas.drawCircle(c, 11, Paint()..color = inkColor);
      final tp = TextPainter(
        text: TextSpan(
          text: '${i + 1}',
          style: const TextStyle(color: offWhiteColor, fontSize: 12, fontWeight: FontWeight.bold),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, c - Offset(tp.width / 2, tp.height / 2));
    }
  }

  @override
  bool shouldRepaint(_OverlayPainter old) => true;
}
