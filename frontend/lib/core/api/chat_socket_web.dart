import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'chat_socket.dart';

ChatSocket createChatSocket() => _WebChatSocket();

/// 브라우저 WebSocket. 주소는 페이지와 같은 서버의 `/api/chats/ws`이고(HTTPS면 `wss://`),
/// 세션 쿠키(`sid`)와 `Origin`은 브라우저가 스스로 싣는다 (05장 33번, D-286).
class _WebChatSocket implements ChatSocket {
  _WebChatSocket() {
    final base = Uri.base;
    final url = Uri(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      host: base.host,
      port: base.hasPort ? base.port : null,
      path: '/api/chats/ws',
    );
    _ws = web.WebSocket(url.toString());
    _ws.onmessage = (web.MessageEvent e) {
      final data = e.data;
      if (_closing || !data.isA<JSString>()) return;
      final event = parseChatEvent((data as JSString).toDart);
      if (event != null) _controller.add(event);
    }.toJS;
    _ws.onclose = (web.CloseEvent e) {
      if (_closing) return;
      _controller.add(ChatClosedEvent(e.code));
      _controller.close();
    }.toJS;
  }

  late final web.WebSocket _ws;
  final _controller = StreamController<ChatEvent>();
  bool _closing = false;

  @override
  Stream<ChatEvent> get events => _controller.stream;

  @override
  void close() {
    if (_closing) return;
    _closing = true;
    _ws.close();
    _controller.close();
  }
}
