import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_error.dart';

/// `/api/...`를 상대경로로 부르는 얇은 클라이언트 (D-11).
/// 배포는 같은 출처, 로컬은 Flutter 개발 서버 프록시(D-164)라 쿠키가 그대로 붙는다.
class ApiClient {
  ApiClient(this._http);

  final http.Client _http;

  Uri _uri(String path, [Map<String, String>? query]) {
    final uri = Uri.base.resolve(path);
    return query == null ? uri : uri.replace(queryParameters: query);
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) =>
      _send(() => _http.get(_uri(path, query)));

  Future<dynamic> post(String path, [Object? body]) => _send(
    () => _http.post(
      _uri(path),
      headers: body == null ? null : const {'Content-Type': 'application/json'},
      body: body == null ? null : jsonEncode(body),
    ),
  );

  Future<dynamic> put(String path, Object body) => _send(
    () => _http.put(
      _uri(path),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    ),
  );

  Future<dynamic> delete(String path) => _send(() => _http.delete(_uri(path)));

  Future<dynamic> _send(Future<http.Response> Function() request) async {
    final http.Response res;
    try {
      res = await request();
    } on http.ClientException {
      throw ApiException(0, networkErrorCode);
    }
    final text = utf8.decode(res.bodyBytes);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return text.isEmpty ? null : jsonDecode(text);
    }
    throw ApiException(res.statusCode, _codeOf(text));
  }

  static String _codeOf(String text) {
    try {
      final body = jsonDecode(text);
      final code = body['error']['code'];
      if (code is String) return code;
    } catch (_) {
      // 에러 모양이 아니면 아래 기본 code
    }
    return 'INTERNAL_ERROR';
  }
}
