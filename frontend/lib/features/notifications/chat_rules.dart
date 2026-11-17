import '../../core/models/message.dart';

/// 채팅 규칙 (07장 2.11, D-303). 위젯이 없는 순수 규칙이라 단위 테스트로 확인한다.

/// 메시지 목록에 새 메시지를 합친다. 같은 `id`는 한 번만 두고 `id` 오름차순으로 돌려준다.
/// 31번 응답과 33번 WebSocket이 같은 메시지를 두 번 줄 수 있어서 쓴다 (05장 33번).
List<ChatMessage> mergeMessages(List<ChatMessage> old, List<ChatMessage> incoming) {
  final byId = {for (final m in old) m.id: m};
  for (final m in incoming) {
    byId.putIfAbsent(m.id, () => m);
  }
  return byId.values.toList()..sort((a, b) => a.id.compareTo(b.id));
}

/// 22번 `peer_user_id`와 같은 번호의 29번 대화 상대 (C-19 ⑧). 이름이 같은 두 계정도 번호로 구분한다.
/// 없으면 null이다. 수락한 사건이 없어 29번에 없는 상대다.
ChatPeer? peerOf(int peerUserId, List<ChatPeer> peers) {
  for (final p in peers) {
    if (p.peerUserId == peerUserId) return p;
  }
  return null;
}

/// 시각을 붙일지. 바로 아래 칸이 같은 쪽([mine])이고 같은 분(HH:mm)이면 아래 칸에만 붙이고 이 칸은 뺀다.
/// 시각이 다르거나 쪽이 다르거나 아래 칸이 없으면 붙인다. [at]이 null이면 붙일 시각이 없다.
bool showTimeStamp(String? at, bool mine, {String? nextAt, bool? nextMine}) {
  if (at == null) return false;
  if (nextAt == null || nextMine != mine) return true;
  String minute(String t) => DateTime.parse(t).toUtc().toIso8601String().substring(0, 16);
  return minute(at) != minute(nextAt);
}

/// 메뉴 [채팅] 배지 수: 기존 수(피해자는 대기 중인 초대 수, 관리자는 할 일 수)에 안 읽은 채팅 수를 더한다 (D-303).
/// 29번이 실패해 [unreadTotal]이 null이면 채팅 수는 0으로 친다.
int chatBadgeCount(int base, int? unreadTotal) => base + (unreadTotal ?? 0);
