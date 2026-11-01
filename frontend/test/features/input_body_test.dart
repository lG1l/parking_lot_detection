import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/features/damage_input/damage_input_page.dart';

void main() {
  const corners = [
    (x: 10, y: 10),
    (x: 100, y: 10),
    (x: 100, y: 50),
    (x: 10, y: 50),
  ];

  Map<String, Object> body({
    required int frontEdge,
    required List<int> edges,
  }) => inputBody(
    stillFrameId: 1,
    detId: 2,
    visible: true,
    damageBox: [20, 20, 40, 40],
    corners: corners,
    frontEdge: frontEdge,
    edges: edges,
  );

  test('11번 본문은 형식 6이고 front_edge를 싣는다 (D-208)', () {
    final b = body(frontEdge: 2, edges: [0]);
    expect(b['schema_version'], 6);
    final damage = b['damage'] as Map<String, Object>;
    expect(damage['front_edge'], 2);
    expect(damage.keys.toSet(), {
      'visible',
      'damage_bbox',
      'floor_corners',
      'front_edge',
      'damage_edges',
    });
  });

  test('앞쪽 변과 파손 변이 같아도 그대로 싣는다 (D-208)', () {
    final damage =
        body(frontEdge: 0, edges: [0])['damage'] as Map<String, Object>;
    expect(damage['front_edge'], 0);
    expect(damage['damage_edges'], [0]);
  });
}
