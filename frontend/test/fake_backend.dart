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

/// "GET /api/videos/1" 같은 키로 응답을 정하는 가짜 백엔드. 부른 순서를 [calls]에 남긴다.
class FakeBackend {
  FakeBackend(this.routes);

  final Map<String, http.Response Function(http.Request req)> routes;
  final calls = <String>[];

  http.Client get client => MockClient((req) async {
    final key = '${req.method} ${req.url.path}';
    calls.add(req.url.query.isEmpty ? key : '$key?${req.url.query}');
    final handler = routes[key];
    if (handler == null) return apiError(404, 'NOT_IN_FAKE');
    return handler(req);
  });
}

class FakeBrowser implements Browser {
  @override
  Future<PickedFile?> pickFile(List<String> extensions) async => null;

  @override
  Future<int> putFile(
    String url,
    PickedFile file, {
    Map<String, String> headers = const {},
    void Function(int sent, int total)? onProgress,
  }) async => 200;

  @override
  Future<Size?> imageNaturalSize(String url) async => const Size(1920, 1080);

  @override
  void log(String message) {}
}

/// 넓은 PC 화면으로 앱을 띄운다.
Future<void> pumpApp(WidgetTester tester, FakeBackend backend, String location) async {
  tester.view.physicalSize = const Size(1400, 1000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        apiProvider.overrideWithValue(Api(ApiClient(backend.client))),
        browserProvider.overrideWithValue(FakeBrowser()),
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
