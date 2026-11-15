import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/api/api_error.dart';
import 'package:parking_lot_frontend/core/api/demo_api.dart';
import 'package:parking_lot_frontend/core/constants.dart';

void main() {
  test('수락 전 사건에는 메시지를 보낼 수 없다 (D-233)', () async {
    final api = DemoApi();
    await api.login('victim01', 'pw');
    await expectLater(
      api.sendMessage(4, '안녕'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'INVALID_STATE')),
    );
  });

  test('사건을 숨겨도 채팅 메시지는 그대로 보인다 (D-287)', () async {
    final api = DemoApi();
    await api.login('parking_admin', 'pw');
    await api.deleteCase(1);
    expect((await api.messages()).where((m) => m.caseId == 1), isNotEmpty);
    await api.sendMessage(1, '숨긴 뒤에도 보냄');
    await api.login('victim01', 'pw');
    expect((await api.messages()).last.body, '숨긴 뒤에도 보냄');
  });

  test('관리자가 보낸 메시지를 피해자로 로그인하면 본다', () async {
    final api = DemoApi();
    await api.login('parking_admin', 'pw');
    await api.sendMessage(1, '  안녕  ');
    await api.login('victim01', 'pw');
    final last = (await api.messages()).last;
    expect(last.body, '안녕');
    expect(last.senderRole, 'admin');
  });

  test('빈 글과 상한을 넘는 글은 422다', () async {
    final api = DemoApi();
    await api.login('parking_admin', 'pw');
    for (final body in ['   ', 'a' * (maxMessageLength + 1)]) {
      await expectLater(
        api.sendMessage(1, body),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'VALIDATION_FAILED')),
      );
    }
  });
}
