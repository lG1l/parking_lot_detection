import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/api/api_error.dart';
import 'package:parking_lot_frontend/core/api/demo_api.dart';

/// 데모 모드의 채팅 29~32번 (05장 5.12). 수락한 사건이 있는 상대만, 읽은 위치는 앞으로만 간다.
void main() {
  Matcher chatNotFound() => throwsA(isA<ApiException>().having((e) => e.code, 'code', 'CHAT_NOT_FOUND'));

  test('수락한 사건이 없는 상대에게는 보낼 수 없다 (D-287)', () async {
    final api = DemoApi();
    await api.login('parking_admin', 'pw');
    await api.createCase('victim09', caseName: '새 사건'); // 피해자가 아직 수락하지 않았다
    await expectLater(api.sendChat(109, '안녕'), chatNotFound());
    expect((await api.chats()).items.map((p) => p.peerName), isNot(contains('victim09')));
  });

  test('사건을 숨겨도 대화와 메시지는 그대로 있다 (D-287)', () async {
    final api = DemoApi();
    await api.login('parking_admin', 'pw');
    await api.deleteCase(1);
    final peer = (await api.chats()).items.firstWhere((p) => p.peerName == 'victim01');
    expect(await api.chatMessages(peer.peerUserId), isNotEmpty);
    await api.sendChat(peer.peerUserId, '숨긴 뒤에도 보냄');
    await api.login('victim01', 'pw');
    final admin = (await api.chats()).items.single;
    expect((await api.chatMessages(admin.peerUserId)).last.body, '숨긴 뒤에도 보냄');
  });

  test('안 읽은 수는 읽음 처리(32번)로 줄고, 더 작은 id로 불러도 되돌아가지 않는다 (D-289)', () async {
    final api = DemoApi();
    await api.login('parking_admin', 'pw');
    final victim = (await api.chats()).items.firstWhere((p) => p.peerName == 'victim01');
    final sent = await api.sendChat(victim.peerUserId, '  안녕  ');
    expect(sent.body, '안녕');
    expect(sent.mine, isTrue);

    await api.login('victim01', 'pw');
    var list = await api.chats();
    final admin = list.items.single;
    expect(admin.unread, 2); // 예시 메시지(관리자가 보낸 것) 1건 + 방금 보낸 1건
    expect(list.unreadTotal, 2);
    final last = (await api.chatMessages(admin.peerUserId)).last;
    expect(last.mine, isFalse);

    await api.markChatRead(admin.peerUserId, last.id);
    expect((await api.chats()).unreadTotal, 0);
    await api.markChatRead(admin.peerUserId, 1);
    expect((await api.chats()).unreadTotal, 0);
  });
}
