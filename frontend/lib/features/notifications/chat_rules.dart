import '../../core/models/account.dart';
import '../../core/models/message.dart';

/// 채팅 규칙 (07장 2.11, D-294). 위젯이 없는 순수 규칙이라 단위 테스트로 확인한다.

/// 한 상대와 묶인 [cases]에 속한 메시지만 시간순(오래된 것이 먼저)으로 모은다.
List<ChatMessage> messagesOfPerson(List<VideoCase> cases, List<ChatMessage> messages) {
  final ids = {for (final c in cases) c.id};
  return messages.where((m) => ids.contains(m.caseId)).toList()..sort((a, b) => a.createdAt.compareTo(b.createdAt));
}

/// 메시지를 보낼 사건: 가장 최근에 수락한 사건. 수락한 사건이 없으면 null (보낼 수 없다).
VideoCase? sendTargetOf(List<VideoCase> cases) {
  final accepted = cases.where((c) => !c.pending).toList();
  if (accepted.isEmpty) return null;
  // 수락 시각이 있으면 그것으로, 없으면(지금 백엔드) 연결 시각으로 견준다
  String at(VideoCase c) => c.acceptedAt ?? c.createdAt;
  return accepted.reduce((a, b) => at(a).compareTo(at(b)) >= 0 ? a : b);
}
