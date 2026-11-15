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
///
/// 오른쪽 위 돋보기 [+]·[−]로 사진을 확대한다 (D-293). 표시 영역의 크기는 그대로이고, 그 안에서 사진만
/// 커져 잘려 보인다. 확대한 상태에서는 드래그로 사진을 옮긴다. 파손 부위를 드래그하는 단계([onDragStart]가
/// 있을 때)만은 드래그가 사각형 그리기이므로 사진이 옮겨지지 않는다.
/// 확대·이동 중에도 누른 위치는 (화면 좌표 + 이동량) ÷ (배율 × 확대) = 원본 좌표로 바꿔 넘긴다.
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

/// 확대 단계. [+]·[−]를 누를 때마다 한 단계씩 움직인다 (D-293).
const stillZoomLevels = [1.0, 1.5, 2.0, 3.0, 4.0];

class _StillCanvasState extends State<StillCanvas> {
  static const _edgeHitPx = 10.0;

  int get _w => widget.natural.width.round();
  int get _h => widget.natural.height.round();

  int _zoomIndex = 0;

  /// 확대한 사진에서 표시 영역 왼쪽 위가 가리키는 위치(확대된 화면 px). 0 ~ 크기 × (확대 − 1).
  Offset _pan = Offset.zero;
  bool _panning = false;

  /// 마지막으로 그린 표시 영역 크기. [+]·[−]로 화면 가운데를 기준으로 확대할 때 쓴다.
  Size _view = Size.zero;

  double get _zoom => stillZoomLevels[_zoomIndex];

  Offset _clampPan(Offset p, Size view, double zoom) => Offset(
    p.dx.clamp(0, view.width * (zoom - 1)),
    p.dy.clamp(0, view.height * (zoom - 1)),
  );

  /// 표시 영역 가운데를 그대로 두고 확대 단계를 바꾼다.
  void _setZoom(int index) {
    final old = _zoom;
    final next = stillZoomLevels[index];
    final center = Offset(_view.width / 2, _view.height / 2);
    setState(() {
      _zoomIndex = index;
      _pan = _clampPan((_pan + center) * (next / old) - center, _view, next);
    });
  }

  /// 화면 좌표 → 확대된 사진 위 좌표.
  Offset _content(Offset local) => local + _pan;

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
        final baseScale = math.min(
          constraints.maxWidth / widget.natural.width,
          widget.maxHeight / widget.natural.height,
        );
        final size = Size(widget.natural.width * baseScale, widget.natural.height * baseScale);
        // 창 폭이 바뀌어 표시 영역이 달라지면 이동량을 새 범위 안으로 넣는다
        if (size != _view) {
          _pan = _view == Size.zero
              ? Offset.zero
              : _clampPan(Offset(_pan.dx * size.width / _view.width, _pan.dy * size.height / _view.height), size, _zoom);
          _view = size;
        }
        final zoom = _zoom;
        final scale = baseScale * zoom; // 원본 1px이 확대된 화면에서 몇 px인지
        final dragging = widget.onDragStart != null;
        final canPan = zoom > 1 && !dragging; // 파손 부위 드래그 단계는 사진을 옮기지 않는다
        final cursor = dragging
            ? SystemMouseCursors.precise
            : canPan
            ? (_panning ? SystemMouseCursors.grabbing : SystemMouseCursors.grab)
            : SystemMouseCursors.click;
        return Center(
          child: SizedBox.fromSize(
            size: size,
            child: Stack(
              children: [
                Positioned.fill(
                  child: MouseRegion(
                    cursor: cursor,
                    onHover: (e) {
                      final c = _content(e.localPosition);
                      widget.onHover?.call(c.dx / scale, c.dy / scale);
                    },
                    child: GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      // 누른 곳부터 드래그로 친다. 사진이 손가락을 그대로 따라오고, 파손 사각형도 누른 점에서 시작한다
                      dragStartBehavior: DragStartBehavior.down,
                      // 트랙패드 두 손가락 스크롤은 받지 않고 페이지 스크롤로 넘긴다
                      supportedDevices: const {
                        PointerDeviceKind.mouse,
                        PointerDeviceKind.touch,
                        PointerDeviceKind.stylus,
                        PointerDeviceKind.invertedStylus,
                      },
                      onTapUp: (e) => _tap(_content(e.localPosition), scale),
                      onPanStart: dragging
                          ? (e) => widget.onDragStart!(_pt(_content(e.localPosition), scale))
                          : canPan
                          ? (_) => setState(() => _panning = true)
                          : null,
                      onPanUpdate: dragging
                          ? (e) => widget.onDragUpdate?.call(_pt(_content(e.localPosition), scale))
                          : canPan
                          ? (e) => setState(() => _pan = _clampPan(_pan - e.delta, size, zoom))
                          : null,
                      onPanEnd: dragging
                          ? (_) => widget.onDragEnd?.call()
                          : canPan
                          ? (_) => setState(() => _panning = false)
                          : null,
                      child: ClipRect(
                        child: Stack(
                          clipBehavior: Clip.hardEdge,
                          children: [
                            Positioned(
                              left: -_pan.dx,
                              top: -_pan.dy,
                              width: size.width * zoom,
                              height: size.height * zoom,
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
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                Positioned(
                  top: 8,
                  right: 8,
                  child: _ZoomButtons(
                    zoom: zoom,
                    onZoomIn: _zoomIndex < stillZoomLevels.length - 1 ? () => _setZoom(_zoomIndex + 1) : null,
                    onZoomOut: _zoomIndex > 0 ? () => _setZoom(_zoomIndex - 1) : null,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// 사진 오른쪽 위의 돋보기 [+]·[−]. 반투명 흰 바탕에 지금 배율을 함께 보인다 (D-293).
class _ZoomButtons extends StatelessWidget {
  const _ZoomButtons({required this.zoom, required this.onZoomIn, required this.onZoomOut});

  final double zoom;
  final VoidCallback? onZoomIn;
  final VoidCallback? onZoomOut;

  @override
  Widget build(BuildContext context) {
    final label = zoom == zoom.roundToDouble() ? '${zoom.round()}배' : '$zoom배';
    return DecoratedBox(
      decoration: BoxDecoration(
        color: offWhiteColor.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: lineColor),
        boxShadow: cardShadow,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: '사진 축소',
            onPressed: onZoomOut,
            color: inkColor,
            icon: const Icon(Icons.zoom_out),
          ),
          SizedBox(
            width: 40,
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: inkColor),
            ),
          ),
          IconButton(
            tooltip: '사진 확대',
            onPressed: onZoomIn,
            color: inkColor,
            icon: const Icon(Icons.zoom_in),
          ),
        ],
      ),
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
        // 그리는 단계: 네 모서리 안을 옅은 빨강으로 채우고 빨간 네 모서리를 그린다 (D-296)
        canvas.drawRect(r, Paint()..color = damageDragColor.withValues(alpha: 0.2));
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
      // 선은 굵기 2(변을 고르는 단계는 3), 번짐 7로 얇게 그린다 (D-295)
      canvas.drawLine(
        a,
        b,
        Paint()
          ..strokeWidth = 7
          ..strokeCap = StrokeCap.round
          ..color = cornerColor.withValues(alpha: _glowAlpha),
      );
      canvas.drawLine(
        a,
        b,
        Paint()
          ..strokeWidth = o.edgesClickable ? 3 : 2
          ..strokeCap = StrokeCap.round
          ..color = cornerColor,
      );
    }
    if (n == 4) {
      // 고른 변은 형광 선: 파손 변은 빨간 형광, 앞쪽 변은 초록 형광 (D-295)
      for (final i in o.edges) {
        _neonLine(canvas, _off(o.corners[i]), _off(o.corners[(i + 1) % 4]), chosenEdgeColor);
      }
      // 파손 변과 같은 변이면 빨강 위에 초록 점선으로 겹쳐 둘 다 보이게 한다 (D-212)
      final front = o.frontEdge;
      if (front != null) {
        _neonLine(
          canvas,
          _off(o.corners[front]),
          _off(o.corners[(front + 1) % 4]),
          frontEdgeColor,
          dashed: o.edges.contains(front),
        );
      }
    }
    // 찍은 점은 번호 없이 점만 그린다 (D-232). 파랑 점에 흰 테두리, 둘레에 옅은 빛 번짐 (캔버스, D-237).
    // 점이 사진을 덜 가리도록 지름 10·번짐 20으로 줄였다 (D-294)
    for (final corner in o.corners) {
      final c = _off(corner);
      canvas.drawCircle(c, 10, Paint()..color = cornerColor.withValues(alpha: _glowAlpha));
      canvas.drawCircle(c, 5, Paint()..color = cornerColor);
      canvas.drawCircle(
        c,
        5,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5
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

  /// 형광 선: 흐린 넓은 빛(굵기 14) 위에 진한 선(굵기 4), 가운데 옅은 흰 줄(굵기 1.5)을 겹친다 (D-295).
  void _neonLine(Canvas canvas, Offset a, Offset b, Color color, {bool dashed = false}) {
    void line(Paint p) => dashed ? _dashedLine(canvas, a, b, p) : canvas.drawLine(a, b, p);
    line(
      Paint()
        ..strokeWidth = 14
        ..strokeCap = StrokeCap.round
        ..color = color.withValues(alpha: 0.45)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4),
    );
    line(
      Paint()
        ..strokeWidth = 4
        ..strokeCap = StrokeCap.round
        ..color = color,
    );
    line(
      Paint()
        ..strokeWidth = 1.5
        ..strokeCap = StrokeCap.round
        ..color = Colors.white.withValues(alpha: 0.6),
    );
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
