import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:parking_lot_frontend/core/api/api.dart';
import 'package:parking_lot_frontend/core/api/api_client.dart';
import 'package:parking_lot_frontend/core/browser/browser.dart';
import 'package:parking_lot_frontend/core/widgets/common.dart';
import 'package:parking_lot_frontend/main.dart';

http.Response json(Object? body, [int status = 200]) => http.Response.bytes(
  body == null ? [] : utf8.encode(jsonEncode(body)),
  status,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

http.Response apiError(int status, String code) => json({
  'error': {'code': code, 'message': 'test'},
}, status);

/// 3번 응답. 역할은 `admin`(관리자) 또는 `victim`(피해자)이다 (D-204).
Map<String, Object?> meJson(String role) => {
  'id': role == 'admin' ? 1 : 2,
  'login_id': role == 'admin' ? 'parking_admin' : 'victim02',
  'name': role == 'admin' ? 'parking_admin' : 'victim02',
  'role': role,
};

/// "GET /api/videos/1" 같은 키로 응답을 정하는 가짜 백엔드. 부른 순서를 [calls]에 남긴다.
/// 로그인한 계정(3번)과 빈 사건 목록(22번)은 따로 정하지 않으면 [role] 계정으로 답한다.
class FakeBackend {
  FakeBackend(Map<String, http.Response Function(http.Request req)> routes, {String role = 'admin'})
    : routes = {
        'GET /api/auth/me': (_) => json(meJson(role)),
        'GET /api/cases': (_) => json({'items': []}),
        ...routes,
      };

  final Map<String, http.Response Function(http.Request req)> routes;
  final calls = <String>[];

  /// 3번(계정)·22번(사건)을 뺀 호출. 화면이 부른 API 순서를 볼 때 쓴다.
  List<String> get screenCalls => [
    for (final c in calls)
      if (c != 'GET /api/auth/me' && c != 'GET /api/cases') c,
  ];

  int count(String call) => calls.where((c) => c == call).length;

  http.Client get client => MockClient((req) async {
    final key = '${req.method} ${req.url.path}';
    calls.add(req.url.query.isEmpty ? key : '$key?${req.url.query}');
    final handler = routes[key];
    if (handler == null) return apiError(404, 'NOT_IN_FAKE');
    return handler(req);
  });
}

class FakeFile implements PickedFile {
  FakeFile(this.name, this.size);

  @override
  final String name;
  @override
  final int size;
  @override
  String get objectUrl => '';
}

class FakeBrowser implements Browser {
  FakeBrowser({this.file, this.putStatus = 200, Map<String, String>? local}) : local = local ?? {};

  /// 파일 고르기 창에서 고를 파일. null이면 취소한 것이다.
  final PickedFile? file;

  /// S3 PUT 결과. 0이면 네트워크가 끊긴 것이다.
  final int putStatus;

  /// localStorage 흉내. 테스트가 값을 미리 넣고, 저장된 값을 확인한다 (D-236).
  final Map<String, String> local;

  @override
  Future<PickedFile?> pickFile(List<String> extensions) async => file;

  @override
  Future<int> putFile(
    String url,
    PickedFile file, {
    Map<String, String> headers = const {},
    void Function(int sent, int total)? onProgress,
  }) async => putStatus;

  @override
  Future<Size?> imageNaturalSize(String url) async => const Size(1920, 1080);

  @override
  void log(String message) {}

  @override
  bool historyBack() => false;

  @override
  String? readLocal(String key) => local[key];

  @override
  void writeLocal(String key, String value) => local[key] = value;
}

/// 넓은 PC 화면으로 앱을 띄운다.
Future<void> pumpApp(WidgetTester tester, FakeBackend backend, String location, {FakeBrowser? browser}) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        apiProvider.overrideWithValue(Api(ApiClient(backend.client))),
        browserProvider.overrideWithValue(browser ?? FakeBrowser()),
        backendNoticeProvider.overrideWithValue(false),
      ],
      child: App(initialLocation: location),
    ),
  );
  await settle(tester);
}

/// 응답과 화면 전환을 기다린다. 대기 화면의 진행 표시는 계속 움직여 pumpAndSettle이 끝나지 않는다.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 20; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// 화면을 내려 주기 조회 타이머를 정리한다.
Future<void> unmount(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
}
