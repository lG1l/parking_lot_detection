import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config.dart';
import '../models/message.dart';
import 'chat_socket_stub.dart' if (dart.library.js_interop) 'chat_socket_web.dart';

/// 33번 `GET /api/chats/ws`로 서버가 보내는 것 (05장 5.12, D-286). 서버에서 화면으로만 간다.
sealed class ChatEvent {}

/// 새 메시지. [peerUserId]는 받는 쪽에서 본 대화 상대다. 내가 다른 탭에서 보낸 메시지도 온다([ChatMessage.mine]).
class ChatMessageEvent extends ChatEvent {
  ChatMessageEvent(this.peerUserId, this.message);

  final int peerUserId;
  final ChatMessage message;
}

/// 연결이 닫혔다. 4401(세션 없음)·4403(Origin 불일치)·4408(연결 수 초과)이거나 그 밖의 끊김이다.
class ChatClosedEvent extends ChatEvent {
  ChatClosedEvent(this.code);

  final int code;
}

/// 33번이 연결을 닫을 때 쓰는 코드 (05장 33번). 이 셋은 다시 연결하지 않는다.
const chatCloseNoSession = 4401; // 세션 쿠키가 없거나 만료, 또는 로그아웃
const chatCloseBadOrigin = 4403; // Origin이 서비스 주소와 다름
const chatCloseTooMany = 4408; // 같은 계정의 연결이 3개를 넘어 가장 오래된 연결을 닫음

/// 33번 연결 하나. 만들면 곧바로 연결을 시작하고, 다시 연결하려면 새로 만든다.
abstract class ChatSocket {
  Stream<ChatEvent> get events;

  /// 연결을 닫는다. 직접 닫았을 때는 [ChatClosedEvent]를 내보내지 않는다.
  void close();
}

/// 만들 때 연결하는 [ChatSocket]을 돌려주는 함수. 테스트는 가짜로 바꿔 끼운다.
typedef ChatSocketFactory = ChatSocket Function();

// 백엔드 연결 필요: 데모는 같은 탭 하나라 상대 메시지가 실시간으로 올 일이 없어 연결을 만들지 않는다 (D-298)
final chatSocketProvider = Provider<ChatSocketFactory>((ref) => useBackend ? createChatSocket : IdleChatSocket.new);

/// 아무것도 오지 않고 닫히지도 않는 연결. 데모와 웹이 아닌 곳(테스트 VM)에서 쓴다.
class IdleChatSocket implements ChatSocket {
  final _controller = StreamController<ChatEvent>();

  @override
  Stream<ChatEvent> get events => _controller.stream;

  @override
  void close() => _controller.close();
}

/// 33번 메시지 한 줄(JSON 글자)을 읽는다. 모르는 `type`이나 깨진 글자는 null이다 (프론트는 무시한다, 05장 33번).
ChatEvent? parseChatEvent(String raw) {
  try {
    final j = jsonDecode(raw) as Map<String, dynamic>;
    if (j['type'] != 'message') return null;
    return ChatMessageEvent(j['peer_user_id'] as int, ChatMessage.fromJson(j['message'] as Map<String, dynamic>));
  } catch (_) {
    return null;
  }
}
