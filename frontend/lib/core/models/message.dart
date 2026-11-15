// 29·30번 응답 (05장 29·30번 초안, D-294). 채팅 메시지 한 건.
import 'account.dart';

class ChatMessage {
  ChatMessage({
    required this.id,
    required this.caseId,
    required this.senderRole,
    required this.body,
    required this.createdAt,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
    id: j['id'] as int,
    caseId: j['case_id'] as int,
    senderRole: j['sender_role'] as String,
    body: j['body'] as String,
    createdAt: j['created_at'] as String,
  );

  final int id;
  final int caseId;

  /// `admin` 또는 `victim`.
  final String senderRole;
  final String body;
  final String createdAt;

  /// 내가 보낸 메시지인지. 내 역할과 보낸 역할이 같으면 내 것이다.
  bool mine(Me me) => senderRole == me.role;
}
