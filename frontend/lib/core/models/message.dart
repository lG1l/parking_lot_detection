// 채팅 모델 (05장 5.12, 29~33번. D-284~D-290). 메시지는 두 계정 쌍에 붙고 사건 번호가 없다.

/// 메시지 한 건. 29·30·31번 응답과 33번 WebSocket 이벤트가 같은 모양이다.
class ChatMessage {
  ChatMessage({required this.id, required this.mine, required this.body, required this.createdAt});

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
    id: j['id'] as int,
    mine: j['mine'] as bool,
    body: j['body'] as String,
    createdAt: j['created_at'] as String,
  );

  /// 클수록 나중에 보낸 메시지다.
  final int id;

  /// 서버가 알려 주는, 내가 보낸 메시지인지.
  final bool mine;
  final String body;
  final String createdAt;
}

/// 29번 목록의 대화 상대 한 줄.
class ChatPeer {
  ChatPeer({required this.peerUserId, required this.peerName, required this.lastMessage, required this.unread});

  factory ChatPeer.fromJson(Map<String, dynamic> j) => ChatPeer(
    peerUserId: j['peer_user_id'] as int,
    peerName: j['peer_name'] as String,
    lastMessage: j['last_message'] == null ? null : ChatMessage.fromJson(j['last_message'] as Map<String, dynamic>),
    unread: j['unread'] as int,
  );

  final int peerUserId;
  final String peerName;

  /// 메시지가 없으면 null.
  final ChatMessage? lastMessage;

  /// 상대가 보낸 메시지 중 내 읽은 위치보다 뒤인 것의 개수 (D-289).
  final int unread;
}

/// 29번 응답.
class ChatList {
  ChatList({required this.items, required this.unreadTotal});

  factory ChatList.fromJson(Map<String, dynamic> j) => ChatList(
    items: [for (final e in j['items'] as List) ChatPeer.fromJson(e as Map<String, dynamic>)],
    unreadTotal: j['unread_total'] as int,
  );

  final List<ChatPeer> items;
  final int unreadTotal;
}
