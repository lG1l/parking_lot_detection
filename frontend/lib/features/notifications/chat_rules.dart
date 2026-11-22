import '../../core/models/account.dart';
import '../../core/models/message.dart';
import 'notification_rules.dart';

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

/// 대화 한 칸. 알림 카드([TalkNotice])이거나 채팅 말풍선([TalkChat])이다 (D-335).
sealed class TalkItem {
  const TalkItem();

  /// 이 칸의 시각. 대화는 이 값의 오름차순이다.
  String get at;
}

class TalkNotice extends TalkItem {
  const TalkNotice(this.notice, this.videoCase, this.at);

  final NoticeMessage notice;
  final VideoCase videoCase;
  @override
  final String at;
}

class TalkChat extends TalkItem {
  const TalkChat(this.message);

  final ChatMessage message;
  @override
  String get at => message.createdAt;
}

/// 알림 카드의 시각. 연결 요청은 22번 `created_at`, 수락은 `accepted_at`, 영상 상태 알림은 8번 `status_changed_at`이다.
/// `status_changed_at`이 없는 이전 서버는 사건의 수락 시각(없으면 요청 시각)을 써서 사건 카드 바로 뒤에 둔다 (D-335).
String noticeAt(NoticeMessage m, VideoCase c) => switch (m) {
  NoticeInvite() => c.createdAt,
  NoticeAccepted() => c.acceptedAt ?? c.createdAt,
  NoticeStatus(:final video) => video.statusChangedAt ?? c.acceptedAt ?? c.createdAt,
};

/// 사건들의 알림 카드와 채팅 말풍선을 시각 오름차순으로 합친다 (D-335).
/// 시각이 같으면 알림이 먼저이고, 알림끼리·채팅끼리는 받은 순서(사건 순, 요청 → 수락 → 영상 / id 순)를 지킨다.
List<TalkItem> talkTimeline(List<(VideoCase, List<NoticeMessage>)> cases, List<ChatMessage> chat) {
  final items = <TalkItem>[
    for (final (c, notices) in cases)
      for (final m in notices) TalkNotice(m, c, noticeAt(m, c)),
    for (final m in chat) TalkChat(m),
  ];
  // List.sort는 안정 정렬이 아니라 같은 시각·같은 종류는 원래 순서로 가른다
  final indexed = [...items.indexed];
  int kind(TalkItem t) => t is TalkNotice ? 0 : 1;
  indexed.sort((a, b) {
    final byTime = DateTime.parse(a.$2.at).compareTo(DateTime.parse(b.$2.at));
    if (byTime != 0) return byTime;
    if (kind(a.$2) != kind(b.$2)) return kind(a.$2) - kind(b.$2);
    return a.$1 - b.$1;
  });
  return [for (final (_, item) in indexed) item];
}
