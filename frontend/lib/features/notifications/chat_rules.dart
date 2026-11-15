import '../../core/models/message.dart';

/// 채팅 규칙 (07장 2.11, D-298). 위젯이 없는 순수 규칙이라 단위 테스트로 확인한다.

/// 메시지 목록에 새 메시지를 합친다. 같은 `id`는 한 번만 두고 `id` 오름차순으로 돌려준다.
/// 31번 응답과 33번 WebSocket이 같은 메시지를 두 번 줄 수 있어서 쓴다 (05장 33번).
List<ChatMessage> mergeMessages(List<ChatMessage> old, List<ChatMessage> incoming) {
  final byId = {for (final m in old) m.id: m};
  for (final m in incoming) {
    byId.putIfAbsent(m.id, () => m);
  }
  return byId.values.toList()..sort((a, b) => a.id.compareTo(b.id));
}

/// 22번의 상대 이름과 같은 이름의 29번 대화 상대. 22번에 상대 계정 ID가 없어 이름으로 짝짓는다 (D-298).
/// 없으면 null이다. 수락한 사건이 없어 29번에 없는 상대다.
ChatPeer? peerOf(String name, List<ChatPeer> peers) {
  for (final p in peers) {
    if (p.peerName == name) return p;
  }
  return null;
}
