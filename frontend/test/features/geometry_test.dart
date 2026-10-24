import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/analysis.dart';
import 'package:parking_lot_frontend/features/damage_input/geometry.dart';

Pt p(int x, int y) => (x: x, y: y);

void main() {
  test('화면 좌표를 원본 픽셀 정수로 되돌리고 이미지 밖은 가장자리로 붙인다', () {
    expect(toImagePoint(100, 50, 0.5, 1920, 1080), p(200, 100));
    expect(toImagePoint(-3, 2000, 0.5, 1920, 1080), p(0, 1080));
  });

  group('겹친 사각형 고르기 (07장 2.6)', () {
    final dets = [
      Detection(1, [0, 0, 100, 100]),
      Detection(2, [20, 20, 60, 60]),
      Detection(3, [200, 200, 300, 300]),
    ];

    test('누른 점을 품는 것 중 가장 작은 것', () {
      expect(pickDetection(dets, 30, 30, null), 2);
      expect(pickDetection(dets, 90, 90, null), 1);
      expect(pickDetection(dets, 150, 150, null), isNull);
    });

    test('다시 누르면 그다음으로 작은 것', () {
      expect(pickDetection(dets, 30, 30, 2), 1);
      expect(pickDetection(dets, 30, 30, 1), 2);
    });
  });

  test('파손 사각형은 차량 안(경계 포함)', () {
    expect(boxInside([10, 10, 50, 50], [10, 10, 50, 50]), isTrue);
    expect(boxInside([9, 10, 50, 50], [10, 10, 50, 50]), isFalse);
    expect(boxFromDrag(p(50, 60), p(10, 20)), [10, 20, 50, 60]);
    expect(boxFromDrag(p(10, 20), p(10, 60)), isNull);
  });

  test('꼬인 네 모서리를 막는다 (05장 5.7 검증 12)', () {
    expect(isTwisted([p(0, 0), p(10, 0), p(10, 10), p(0, 10)]), isFalse);
    expect(isTwisted([p(0, 0), p(10, 10), p(10, 0), p(0, 10)]), isTrue);
    // 볼록하지 않아도 꼬이지만 않으면 된다
    expect(isTwisted([p(0, 0), p(10, 0), p(5, 3), p(0, 10)]), isFalse);
  });

  group('파손 변은 1개 또는 이웃한 2개 (05장 5.7 검증 13)', () {
    test('이웃한 변은 더하고 마주 보는 변은 막는다', () {
      expect(toggleEdge([], 0).edges, [0]);
      expect(toggleEdge([0], 3).edges, [0, 3]);
      final r = toggleEdge([0], 2);
      expect(r.blocked, isTrue);
      expect(r.edges, [0]);
    });

    test('다시 누르면 뺀다', () {
      expect(toggleEdge([0, 1], 1).edges, [0]);
    });
  });
}
