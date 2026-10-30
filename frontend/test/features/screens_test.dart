import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:parking_lot_frontend/core/constants.dart';

import '../fake_backend.dart';

Map<String, Object?> video(String status, {Map<String, Object?> extra = const {}}) => {
  'video_id': 7,
  'original_filename': 'CH01.mp4',
  'status': status,
  'input_done': false,
  'raw_deleted': false,
  'masked_deleted': false,
  'created_at': '2026-10-20T09:00:00+09:00',
  'duration_sec': 3600.0,
  'view_expires_at': '2026-11-19T10:00:00+09:00',
  ...extra,
};

Map<String, Object?> lists({int mainRemaining = 10, bool pfEmpty = true}) => {
  'main': {'latest_batch_no': 1, 'remaining': mainRemaining, 'done': false, 'unavailable': 0},
  'parse_failed': pfEmpty
      ? {'latest_batch_no': null, 'remaining': 0, 'done': true, 'unavailable': 0}
      : {'latest_batch_no': 1, 'remaining': 2, 'done': false, 'unavailable': 0},
};

void main() {
  testWidgets('로그인하지 않았으면 로그인 화면, 로그인하면 영상 목록 (2.1, 2.2)', (tester) async {
    final backend = FakeBackend({
      'GET /api/auth/me': (_) => apiError(401, 'UNAUTHENTICATED'),
      'POST /api/auth/login': (req) {
        final body = jsonDecode(req.body);
        return body['password'] == 'pw'
            ? json({'id': 1, 'login_id': 'demo', 'name': '시연용'})
            : apiError(401, 'LOGIN_FAILED');
      },
      'GET /api/videos': (_) => json([
        {
          'video_id': 7,
          'original_filename': 'CH01.mp4',
          'status': 'ready',
          'masked_deleted': false,
          'created_at': '2026-10-20T09:00:00+09:00',
          'view_expires_at': '2026-11-19T10:00:00+09:00',
        },
      ]),
    });
    await pumpApp(tester, backend, '/');
    expect(find.widgetWithText(FilledButton, '로그인'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextField, '아이디'), 'demo');
    await tester.enterText(find.widgetWithText(TextField, '비밀번호'), 'wrong');
    await tester.tap(find.widgetWithText(FilledButton, '로그인'));
    await settle(tester);
    expect(find.text('아이디 또는 비밀번호가 올바르지 않습니다.'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextField, '비밀번호'), 'pw');
    await tester.tap(find.widgetWithText(FilledButton, '로그인'));
    await settle(tester);
    expect(find.text('CH01.mp4'), findsOneWidget);
    expect(find.text('확인 가능'), findsOneWidget);
    expect(find.text('2026-11-19 10:00까지 열람 가능'), findsOneWidget);
  });

  testWidgets('입력필요순 정렬은 서버를 다시 부르지 않고 순서만 바꾼다 (2.2, D-183, D-186)', (tester) async {
    Map<String, Object?> item(int id, String name, String status, {bool expired = false}) => {
      'video_id': id,
      'original_filename': name,
      'status': status,
      'masked_deleted': expired,
      'created_at': '2026-10-20T09:00:00+09:00',
      'view_expires_at': '2026-11-19T10:00:00+09:00',
    };
    final backend = FakeBackend({
      'GET /api/auth/me': (_) => json({'id': 1, 'login_id': 'demo', 'name': '시연용'}),
      'GET /api/videos': (_) => json([
        item(1, 'A_끝남.mp4', 'finished'),
        item(2, 'B_기다림.mp4', 'queued'),
        item(3, 'C_입력필요.mp4', 'stage1_done'),
        item(4, 'D_확인가능.mp4', 'ready'),
        item(5, 'E_실패.mp4', 'failed'),
        item(6, 'F_끝남.mp4', 'exhausted'),
        item(7, 'G_종료됨.mp4', 'finished', expired: true),
      ]),
    });
    await pumpApp(tester, backend, '/videos');
    await settle(tester);

    double top(String name) => tester.getTopLeft(find.text(name)).dy;
    List<String> order() {
      final names = ['A_끝남.mp4', 'B_기다림.mp4', 'C_입력필요.mp4', 'D_확인가능.mp4', 'E_실패.mp4', 'F_끝남.mp4', 'G_종료됨.mp4'];
      return (names..sort((a, b) => top(a).compareTo(top(b)))).map((n) => n[0]).toList();
    }

    expect(order(), ['A', 'B', 'C', 'D', 'E', 'F', 'G']);
    expect(find.text('확인 끝남'), findsNWidgets(2)); // finished·exhausted 같은 이름
    expect(find.text('종료됨'), findsOneWidget);

    await tester.tap(find.text('최신순'));
    await settle(tester);
    await tester.tap(find.text('입력필요순').last);
    await settle(tester);
    expect(order(), ['C', 'D', 'E', 'B', 'A', 'F', 'G']);

    await tester.tap(find.text('입력필요순'));
    await settle(tester);
    await tester.tap(find.text('최신순').last);
    await settle(tester);
    expect(order(), ['A', 'B', 'C', 'D', 'E', 'F', 'G']);

    expect(backend.calls.where((c) => c == 'GET /api/videos').length, 1);
  });

  testWidgets('빈 칸이면 서버를 부르지 않고 안내를 보인다 (2.1, D-182)', (tester) async {
    final backend = FakeBackend({'GET /api/auth/me': (_) => apiError(401, 'UNAUTHENTICATED')});
    await pumpApp(tester, backend, '/');

    await tester.tap(find.widgetWithText(FilledButton, '로그인'));
    await settle(tester);
    expect(find.text('아이디를 입력하세요'), findsOneWidget);
    expect(find.text('비밀번호를 입력하세요'), findsOneWidget);
    expect(backend.calls, isNot(contains('POST /api/auth/login')));

    await tester.enterText(find.widgetWithText(TextField, '아이디'), 'demo');
    await tester.pump();
    expect(find.text('아이디를 입력하세요'), findsNothing);
    expect(find.text('비밀번호를 입력하세요'), findsOneWidget);
  });

  testWidgets('비밀번호 칸의 눈 아이콘으로 보기와 숨기기를 바꾼다 (2.1, D-182)', (tester) async {
    final backend = FakeBackend({'GET /api/auth/me': (_) => apiError(401, 'UNAUTHENTICATED')});
    await pumpApp(tester, backend, '/');
    bool obscured() =>
        tester.widget<TextField>(find.widgetWithText(TextField, '비밀번호')).obscureText;
    expect(obscured(), isTrue);

    await tester.tap(find.byTooltip('비밀번호 보기'));
    await tester.pump();
    expect(obscured(), isFalse);

    await tester.tap(find.byTooltip('비밀번호 숨기기'));
    await tester.pump();
    expect(obscured(), isTrue);
  });

  testWidgets('업로드 링크는 버튼을 눌렀을 때만 발급한다 (2.3)', (tester) async {
    final backend = FakeBackend({
      'POST /api/upload-links': (_) =>
          json({'token': 'tok123', 'expires_at': '2026-10-23T14:03:00+09:00'}, 201),
    });
    await pumpApp(tester, backend, '/videos/upload-link');
    expect(backend.calls, isEmpty);

    await tester.tap(find.text('링크 발급'));
    await settle(tester);
    expect(backend.calls, ['POST /api/upload-links']);
    expect(find.textContaining('#/upload/tok123'), findsOneWidget);
    expect(find.text('링크는 2026-10-23 14:03까지 한 번만 쓸 수 있습니다.'), findsOneWidget);
  });

  testWidgets('상단 바 로고를 누르면 영상 목록으로 간다 (D-185)', (tester) async {
    final backend = FakeBackend({'GET /api/videos': (_) => json([])});
    await pumpApp(tester, backend, '/videos/upload-link');
    await tester.tap(find.text(serviceName));
    await settle(tester);
    expect(find.textContaining('아직 올라온 영상이 없습니다'), findsOneWidget);
  });

  testWidgets('[←]는 이전 기록이 없으면 영상 목록으로 가고, 영상 목록에는 [←]가 없다 (D-185)', (tester) async {
    final backend = FakeBackend({'GET /api/videos': (_) => json([])});
    await pumpApp(tester, backend, '/videos/upload-link');
    await tester.tap(find.byTooltip('이전 화면'));
    await settle(tester);
    expect(find.textContaining('아직 올라온 영상이 없습니다'), findsOneWidget);
    expect(find.byTooltip('이전 화면'), findsNothing);
  });

  testWidgets('관리자 업로드 화면의 로고는 눌러도 그대로다 (D-185)', (tester) async {
    final backend = FakeBackend({
      'GET /api/uploads/tok': (_) => apiError(410, 'UPLOAD_TOKEN_USED'),
    });
    await pumpApp(tester, backend, '/upload/tok');
    await tester.tap(find.text(serviceName));
    await settle(tester);
    expect(find.text('영상 업로드'), findsOneWidget);
  });

  testWidgets('대기 중이면 앞에 N건을 보이고 5초마다 다시 부른다 (2.5)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('queued', extra: {'queue_ahead': 2})),
    });
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('처리를 대기중입니다. 앞에 2건이 있습니다.'), findsOneWidget);
    expect(backend.calls.length, 1);

    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(backend.calls.length, 2);
    await unmount(tester);
  });

  testWidgets('실패하면 남은 횟수와 [분석 다시 시도], 접수되면 대기 화면 (2.5, D-112)', (tester) async {
    var retried = false;
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(
        retried
            ? video('stage2_running')
            : video(
                'failed',
                extra: {'error_kind': 'temporary', 'can_retry': true, 'retry_left': 2},
              ),
      ),
      'POST /api/videos/7/retry': (_) {
        retried = true;
        return json({'status': 'stage2_running', 'retry_left': 1}, 202);
      },
    });
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('다시 시도 가능: 2회 남음'), findsOneWidget);

    await tester.tap(find.text('분석 다시 시도'));
    await settle(tester);
    expect(find.text('영상을 분석하고 있습니다. 24시간 영상이면 약 20분 걸립니다.'), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('후보 0건으로 끝나면 사건 없음이 아니라 탐지 안 됨으로 쓴다 (2.8)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) =>
          json(video('exhausted', extra: {'candidate_total': 0, 'candidate_unavailable': 0})),
    });
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('후보 구간이 탐지되지 않았습니다'), findsOneWidget);
  });

  testWidgets('위탁계약 체크 3개를 모두 해야 영상 선택으로 넘어간다 (2.4)', (tester) async {
    final backend = FakeBackend({
      'GET /api/uploads/tok': (_) => json({'expires_at': '2026-10-23T14:03:00+09:00'}),
    });
    await pumpApp(tester, backend, '/upload/tok');
    final agree = find.widgetWithText(FilledButton, '동의하고 영상 선택하기');
    expect(tester.widget<FilledButton>(agree).onPressed, isNull);

    for (final box in find.byType(CheckboxListTile).evaluate().toList()) {
      await tester.ensureVisible(find.byWidget(box.widget));
      await tester.tap(find.byWidget(box.widget));
      await tester.pump();
    }
    expect(tester.widget<FilledButton>(agree).onPressed, isNotNull);
    await tester.ensureVisible(agree);
    await tester.tap(agree);
    await settle(tester);
    expect(find.text('파일 선택'), findsOneWidget);
    expect(backend.calls, ['GET /api/uploads/tok']); // 동의는 따로 저장하지 않는다
  });

  testWidgets('쓴 링크면 동의 단계 없이 안내만 (2.4)', (tester) async {
    final backend = FakeBackend({
      'GET /api/uploads/tok': (_) => apiError(410, 'UPLOAD_TOKEN_USED'),
    });
    await pumpApp(tester, backend, '/upload/tok');
    expect(find.text('만료되거나 이미 사용이 완료된 링크입니다. 피해자에게 새 링크를 받아 주세요.'), findsOneWidget);
    expect(find.byType(CheckboxListTile), findsNothing);
  });

  testWidgets('[찾음]으로 고정하면 확정됨 표시와 [확인 끝내기]가 생긴다 (2.7)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('ready')),
      'GET /api/videos/7/batch': (_) => json({
        'list': 'main',
        'batch_no': 1,
        'unavailable': 1,
        'candidates': [
          {
            'candidate_clip_id': 1187,
            'rank': 1,
            'vlm_score': 87,
            'start_sec': 13235.0,
            'end_sec': 13265.0,
            'clip_url': 'http://x/1187.mp4',
          },
        ],
        'lists': lists(),
      }),
      'GET /api/videos/7/pin': (_) => json([]),
      'POST /api/videos/7/pin': (_) => json([
        {
          'candidate_clip_id': 1187,
          'start_sec': 13235.0,
          'end_sec': 13265.0,
          'est_start_at': null,
          'est_end_at': null,
          'clip_url': 'http://x/1187.mp4',
          'pinned_at': '2026-10-20T15:20:11+09:00',
        },
      ]),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    expect(find.text('점수 87'), findsOneWidget);
    expect(find.text('후보 10'), findsOneWidget);
    expect(find.text('점수 미산출 (0)'), findsOneWidget);
    expect(find.text('이 묶음에 영상을 준비하지 못해 볼 수 없는 후보가 1건 있습니다.'), findsOneWidget);
    expect(find.text('다음 묶음 받기'), findsOneWidget);
    expect(find.text('확인 끝내기'), findsNothing);

    await tester.tap(find.widgetWithText(FilledButton, '찾음'));
    await settle(tester);
    await tester.tap(find.widgetWithText(FilledButton, '고정'));
    await settle(tester);
    expect(find.text('확정됨'), findsOneWidget);
    expect(find.text('확인 끝내기'), findsOneWidget);
    expect(backend.calls, contains('POST /api/videos/7/pin'));
  });

  testWidgets('결과 화면은 원본 기준 시간과 추정 실제 시각을 보인다 (2.9)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('finished')),
      'GET /api/videos/7/pin': (_) => json([
        {
          'candidate_clip_id': 1187,
          'start_sec': 13235.0,
          'end_sec': 13265.0,
          'est_start_at': '2026-09-17T03:40:35+09:00',
          'est_end_at': '2026-09-17T03:41:05+09:00',
          'clip_url': 'http://x/1187.mp4',
          'pinned_at': '2026-10-20T15:20:11+09:00',
        },
      ]),
    });
    await pumpApp(tester, backend, '/videos/7/results');
    expect(find.text('03:40:35 ~ 03:41:05'), findsOneWidget);
    expect(find.text('2026-09-17 03:40:35 ~ 03:41:05 (관리자 입력 기준 추정)'), findsOneWidget);
    expect(find.text('이 결과는 2026-11-19 10:00까지 열람 가능합니다.'), findsOneWidget);
  });

  testWidgets('열람기한이 지나 MASKED_EXPIRED를 받으면 보관 기간 종료 안내로 간다 (2.10)', (tester) async {
    // 파기 작업이 돌기 전이라 9번은 아직 masked_deleted가 false다
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('ready')),
      'GET /api/videos/7/batch': (_) => apiError(409, 'MASKED_EXPIRED'),
      'GET /api/videos/7/pin': (_) => apiError(409, 'MASKED_EXPIRED'),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    expect(
      find.text('업로드 완료 후 30일이 지나 보관 기간이 끝났습니다. 영상은 안전하게 삭제되었습니다.'),
      findsOneWidget,
    );
  });

  testWidgets('입력을 마친 영상은 입력 화면을 열지 않는다 (2.6, D-66)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) =>
          json(video('stage1_done', extra: {'input_done': true, 'queue_ahead': 0})),
    });
    await pumpApp(tester, backend, '/videos/7/input');
    expect(find.textContaining('입력을 저장했습니다.'), findsOneWidget);
    expect(backend.calls, isNot(contains('GET /api/videos/7/still')));
    await unmount(tester);
  });

  testWidgets('탐지 0건이면 재업로드 안내 (2.6, D-65)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('stage1_done')),
      'GET /api/videos/7/still': (_) => json({
        'still_frame_id': 305,
        't_sec': 0.0,
        'image_url': 'http://x/0.jpg',
        'detections': [],
      }),
    });
    await pumpApp(tester, backend, '/videos/7/input');
    expect(find.textContaining('이 장면에서 본인 차량을 찾지 못했습니다.'), findsOneWidget);
    expect(find.text('업로드 링크 받기'), findsOneWidget);
  });
}
