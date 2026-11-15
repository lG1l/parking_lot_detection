import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/message.dart';
import 'package:parking_lot_frontend/features/notifications/chat_rules.dart';

ChatMessage _m(int id) => ChatMessage(id: id, mine: false, body: '$id', createdAt: '2026-11-15T10:00:00Z');

void main() {
  test('메시지를 합칠 때 같은 id는 한 번만 두고 id 오름차순이다 (05장 33번)', () {
    final out = mergeMessages([_m(1), _m(2)], [_m(3), _m(2)]);
    expect(out.map((m) => m.id), [1, 2, 3]);
  });
}
