import 'chat_socket.dart';

/// 웹이 아닌 곳(테스트 VM)에서 쓰는 빈 구현. 테스트는 가짜로 바꿔 끼운다.
ChatSocket createChatSocket() => IdleChatSocket();
