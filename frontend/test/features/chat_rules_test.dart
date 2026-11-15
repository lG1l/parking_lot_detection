import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/account.dart';
import 'package:parking_lot_frontend/core/models/message.dart';
import 'package:parking_lot_frontend/features/notifications/chat_rules.dart';

VideoCase _case(int id, {String? acceptedAt, bool pending = false}) => VideoCase(
  id: id,
  victimName: 'v',
  createdAt: '2026-11-0${id}T00:00:00Z',
  acceptedAt: acceptedAt,
  pending: pending,
);

void main() {
  test('보낼 사건은 가장 최근에 수락한 사건이고, 수락한 사건이 없으면 null이다 (D-290)', () {
    final cases = [
      _case(1, acceptedAt: '2026-11-02T00:00:00Z'),
      _case(2, acceptedAt: '2026-11-05T00:00:00Z'),
      _case(3, pending: true),
    ];
    expect(sendTargetOf(cases)?.id, 2);
    expect(sendTargetOf([_case(3, pending: true)]), isNull);
  });

  test('그 사람의 사건 메시지만 시간순으로 모은다', () {
    ChatMessage m(int id, int caseId, String at) =>
        ChatMessage(id: id, caseId: caseId, senderRole: 'admin', body: '$id', createdAt: at);
    final out = messagesOfPerson(
      [_case(1), _case(2)],
      [m(1, 2, '2026-11-03T00:00:00Z'), m(2, 9, '2026-11-01T00:00:00Z'), m(3, 1, '2026-11-02T00:00:00Z')],
    );
    expect(out.map((e) => e.id), [3, 1]);
  });
}
