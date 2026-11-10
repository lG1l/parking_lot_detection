import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:parking_lot_frontend/features/damage_input/still_canvas.dart';

import '../fake_backend.dart';

Map<String, Object?> video(String status, {Map<String, Object?> extra = const {}}) => {
  'video_id': 7,
  'case_id': 3,
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

Map<String, Object?> case3() => {
  'id': 3,
  'admin_name': 'parking_admin',
  'victim_name': 'victim02',
  'created_at': '2026-11-01T14:03:00+09:00',
};

/// 위탁계약 체크 3개를 하고 [동의하고 영상 선택하기]를 누른다 (2.4).
Future<void> agreeUpload(WidgetTester tester) async {
  for (final box in find.byType(CheckboxListTile).evaluate().toList()) {
    await tester.ensureVisible(find.byWidget(box.widget));
    await tester.tap(find.byWidget(box.widget));
    await tester.pump();
  }
  final agree = find.widgetWithText(FilledButton, '동의하고 영상 선택하기');
  await tester.ensureVisible(agree);
  await tester.tap(agree);
  await settle(tester);
}

/// 관리·감독 안내창에서 체크하고 [동의하고 열람]을 누른다 (2.7).
Future<void> agreeSupervision(WidgetTester tester) async {
  await tester.tap(find.byType(CheckboxListTile));
  await tester.pump();
  await tester.tap(find.widgetWithText(FilledButton, '동의하고 열람'));
  await settle(tester);
}

void main() {
  testWidgets('로그인하지 않았으면 로그인 화면, 로그인하면 영상 목록 (2.1, 2.2)', (tester) async {
    var loggedIn = false;
    final backend = FakeBackend({
      'GET /api/auth/me': (_) => loggedIn ? json(meJson('admin')) : apiError(401, 'UNAUTHENTICATED'),
      'POST /api/auth/login': (req) {
        final body = jsonDecode(req.body);
        if (body['password'] != 'pw') return apiError(401, 'LOGIN_FAILED');
        loggedIn = true;
        return json(meJson('admin'));
      },
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
      'GET /api/videos': (_) => json([
        {
          'video_id': 7,
          'case_id': 3,
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

    await tester.enterText(find.byType(TextField).first, 'parking_admin');
    await tester.enterText(find.byType(TextField).last, 'wrong');
    await tester.tap(find.widgetWithText(FilledButton, '로그인'));
    await settle(tester);
    expect(find.text('아이디 또는 비밀번호가 올바르지 않습니다.'), findsOneWidget);

    await tester.enterText(find.byType(TextField).last, 'pw');
    await tester.tap(find.widgetWithText(FilledButton, '로그인'));
    await settle(tester);
    expect(find.text('사건 1건'), findsOneWidget);
    expect(find.text('CH01.mp4'), findsOneWidget);
    expect(find.text('victim02'), findsOneWidget); // 피해자 칸 (22번)
    expect(find.text('후보 선택 가능'), findsOneWidget);
    expect(find.text('2026-10-20'), findsOneWidget); // 업로드 날짜 (created_at)
    expect(find.text('2026-11-19'), findsOneWidget); // 열람기한은 날짜만 (D-190)
    expect(find.text('관리자 계정'), findsOneWidget);
  });

  testWidgets('표 머리를 누르면 서버를 다시 부르지 않고 그 칸으로 정렬한다 (2.2, D-211)', (tester) async {
    Map<String, Object?> item(int id, String name, String status, {bool expired = false}) => {
      'video_id': id,
      'case_id': 3,
      'original_filename': name,
      'status': status,
      'masked_deleted': expired,
      'created_at': '2026-10-${29 - id}T09:00:00+09:00', // A가 가장 최근
      'view_expires_at': '2026-11-19T10:00:00+09:00',
    };
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([
        item(7, 'G_종료됨.mp4', 'finished', expired: true),
        item(3, 'C_입력필요.mp4', 'stage1_done'),
        item(1, 'A_끝남.mp4', 'finished'),
        item(5, 'E_실패.mp4', 'failed'),
        item(2, 'B_기다림.mp4', 'queued'),
        item(6, 'F_끝남.mp4', 'exhausted'),
        item(4, 'D_확인가능.mp4', 'ready'),
      ]),
    });
    await pumpApp(tester, backend, '/videos');

    double top(String name) => tester.getTopLeft(find.text(name)).dy;
    List<String> order() {
      final names = ['A_끝남.mp4', 'B_기다림.mp4', 'C_입력필요.mp4', 'D_확인가능.mp4', 'E_실패.mp4', 'F_끝남.mp4', 'G_종료됨.mp4'];
      return (names..sort((a, b) => top(a).compareTo(top(b)))).map((n) => n[0]).toList();
    }

    expect(order(), ['A', 'B', 'C', 'D', 'E', 'F', 'G']); // 처음은 업로드 날짜 최신순
    expect(find.text('확인 완료'), findsNWidgets(2)); // finished·exhausted 같은 이름
    expect(find.text('종료됨'), findsOneWidget);

    await tester.tap(find.text('상태'));
    await settle(tester);
    expect(order(), ['C', 'D', 'E', 'B', 'A', 'F', 'G']);

    await tester.tap(find.text('업로드 날짜'));
    await settle(tester);
    expect(order(), ['A', 'B', 'C', 'D', 'E', 'F', 'G']);

    expect(backend.count('GET /api/videos'), 1);
  });

  testWidgets('창 폭을 줄여도 목록 칸이 넘치지 않는다 (2.2)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([
        video('stage1_done'),
        {...video('ready'), 'video_id': 8},
        {...video('upload_failed'), 'video_id': 9, 'view_expires_at': null},
      ]),
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
    });
    await pumpApp(tester, backend, '/videos');
    // 표가 펼쳐지는 폭(960 이상)과 접히는 폭을 차례로 본다. 넘치면 테스트가 실패한다
    for (final width in [1400.0, 1100.0, 961.0, 959.0, 800.0, 721.0, 600.0, 390.0]) {
      tester.view.physicalSize = Size(width, 1000);
      await settle(tester);
      expect(tester.takeException(), isNull, reason: '폭 $width');
      expect(find.textContaining('2026-10-20'), findsNWidgets(3), reason: '폭 $width'); // 접어도 업로드 날짜는 보인다
    }
  });

  testWidgets('연결만 한 사건은 [업로드 필요] 줄로 보이고 누르면 업로드 화면 (2.2, D-211)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
    });
    await pumpApp(tester, backend, '/videos');
    expect(find.text('아직 올린 영상이 없습니다'), findsOneWidget);
    expect(find.text('업로드 필요'), findsOneWidget);

    await tester.tap(find.text('업로드 필요'));
    await settle(tester);
    expect(find.text('CCTV 영상 올리기'), findsOneWidget);
    expect(find.text('피해자 victim02'), findsOneWidget); // 영상 올리기 | 피해자 ○○ | 열람기한
    expect(find.text('동의하고 영상 선택하기'), findsOneWidget);
  });

  testWidgets('피해자 계정은 영상 없는 사건을 [업로드 중] 줄로 보고 누를 수 없다 (2.2, D-226)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos');
    expect(find.text('아직 올라온 영상이 없습니다'), findsNothing);
    expect(find.text('영상 1건'), findsOneWidget); // 제목은 줄 수다
    expect(find.text('업로드 중'), findsOneWidget);
    expect(find.text('parking_admin'), findsOneWidget);

    await tester.tap(find.text('업로드 중'));
    await settle(tester);
    expect(find.text('CCTV 영상 올리기'), findsNothing);
    expect(find.text('업로드 중'), findsOneWidget);
  });

  testWidgets('피해자 계정 목록은 관리자 칸과 안내 줄, 연결 메뉴 없음 (2.2, D-204)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([video('ready')]),
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos');
    expect(find.text('영상 1건'), findsOneWidget);
    expect(find.text('관리자'), findsOneWidget); // 표 머리
    expect(find.text('parking_admin'), findsOneWidget);
    expect(find.text('분석 완료'), findsOneWidget); // 피해자는 후보 선택 단계를 보지 않는다
    expect(find.textContaining('영상은 주차장 관리자가 올립니다.'), findsOneWidget);
    expect(find.text('사건 관계자 연결'), findsNothing);
    expect(find.text('관리자 계정'), findsNothing);
  });

  testWidgets('빈 칸이면 서버를 부르지 않고 안내를 보인다 (2.1, D-182)', (tester) async {
    final backend = FakeBackend({'GET /api/auth/me': (_) => apiError(401, 'UNAUTHENTICATED')});
    await pumpApp(tester, backend, '/');

    await tester.tap(find.widgetWithText(FilledButton, '로그인'));
    await settle(tester);
    expect(find.text('아이디를 입력하세요'), findsOneWidget);
    expect(find.text('비밀번호를 입력하세요'), findsOneWidget);
    expect(backend.calls, isNot(contains('POST /api/auth/login')));

    await tester.enterText(find.byType(TextField).first, 'demo');
    await tester.pump();
    expect(find.text('아이디를 입력하세요'), findsNothing);
    expect(find.text('비밀번호를 입력하세요'), findsOneWidget);
  });

  testWidgets('비밀번호를 비우고 Enter를 눌러도 그 칸에서 바로 다시 입력할 수 있다 (2.1)', (tester) async {
    final backend = FakeBackend({'GET /api/auth/me': (_) => apiError(401, 'UNAUTHENTICATED')});
    await pumpApp(tester, backend, '/');
    await tester.enterText(find.byType(TextField).first, 'demo');
    await tester.tap(find.byType(TextField).last);
    await tester.pump();
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await settle(tester);
    expect(find.text('비밀번호를 입력하세요'), findsOneWidget);
    expect(tester.widget<EditableText>(find.byType(EditableText).last).focusNode.hasFocus, isTrue);

    tester.testTextInput.enterText('pw');
    await tester.pump();
    expect(tester.widget<TextField>(find.byType(TextField).last).controller!.text, 'pw');
    expect(find.text('비밀번호를 입력하세요'), findsNothing);
  });

  testWidgets('비밀번호 칸의 눈 아이콘으로 보기와 숨기기를 바꾼다 (2.1, D-182)', (tester) async {
    final backend = FakeBackend({'GET /api/auth/me': (_) => apiError(401, 'UNAUTHENTICATED')});
    await pumpApp(tester, backend, '/');
    bool obscured() => tester.widget<TextField>(find.byType(TextField).last).obscureText;
    expect(obscured(), isTrue);

    await tester.tap(find.byTooltip('비밀번호 보기'));
    await tester.pump();
    expect(obscured(), isFalse);

    await tester.tap(find.byTooltip('비밀번호 숨기기'));
    await tester.pump();
    expect(obscured(), isTrue);
  });

  testWidgets('[연결]하면 24번 확인창 뒤 21번으로 사건을 만들고 그 사건의 업로드 화면으로 간다 (2.3, D-206)', (tester) async {
    final backend = FakeBackend({
      'GET /api/users/lookup': (req) {
        expect(req.url.queryParameters['login_id'], 'victim02');
        return json({'login_id': 'victim02', 'masked_name': '홍*동'});
      },
      'POST /api/cases': (req) {
        expect(jsonDecode(req.body), {'victim_login_id': 'victim02'});
        return json({'id': 3, 'victim_name': 'victim02', 'created_at': '2026-11-01T14:03:00+09:00'}, 201);
      },
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
    });
    await pumpApp(tester, backend, '/cases/new');
    expect(backend.screenCalls, isEmpty); // 열 때는 부르지 않는다

    await tester.enterText(find.byType(TextField), 'victim02');
    await tester.tap(find.widgetWithText(FilledButton, '연결'));
    await settle(tester);
    expect(find.text('피해자 계정을 연결할까요?'), findsOneWidget);
    expect(find.textContaining('victim02 (홍*동)'), findsOneWidget);
    expect(backend.calls, isNot(contains('POST /api/cases'))); // 확인창에서 한 번 더 눌러야 만든다

    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.widgetWithText(FilledButton, '연결')));
    await settle(tester);
    expect(backend.calls, contains('POST /api/cases'));
    expect(find.text('피해자 victim02'), findsOneWidget); // 영상 올리기 | 피해자 ○○ | 열람기한
    expect(find.text('동의하고 영상 선택하기'), findsOneWidget);
  });

  testWidgets('없는 피해자 아이디면 칸 아래에 안내 (2.3)', (tester) async {
    final backend = FakeBackend({'GET /api/users/lookup': (_) => apiError(422, 'INVITEE_INVALID')});
    await pumpApp(tester, backend, '/cases/new');
    await tester.enterText(find.byType(TextField), 'victim99');
    await tester.tap(find.widgetWithText(FilledButton, '연결'));
    await settle(tester);
    expect(find.text('피해자 계정을 찾을 수 없습니다. 아이디를 다시 확인해 주세요.'), findsOneWidget);
    expect(find.text('사건 관계자 연결'), findsWidgets); // 화면에 머문다
  });

  testWidgets('피해자 계정은 사건 관계자 연결 화면에 들어가지 못한다 (D-204)', (tester) async {
    final backend = FakeBackend({'GET /api/videos': (_) => json([])}, role: 'victim');
    await pumpApp(tester, backend, '/cases/new');
    expect(find.text('아직 올라온 영상이 없습니다'), findsOneWidget);
  });

  testWidgets('상단 바 로고는 그림이라 눌러도 그대로다 (D-190)', (tester) async {
    final backend = FakeBackend({});
    await pumpApp(tester, backend, '/cases/new');
    await tester.tap(find.bySemanticsLabel('서비스 로고'), warnIfMissed: false);
    await settle(tester);
    expect(find.text('피해자 아이디'), findsOneWidget);
    expect(backend.screenCalls, isEmpty);
  });

  testWidgets('관리자 상단 바 메뉴로 영상 목록과 사건 관계자 연결을 오간다 (D-211)', (tester) async {
    final backend = FakeBackend({'GET /api/videos': (_) => json([])});
    await pumpApp(tester, backend, '/cases/new');
    await tester.tap(find.widgetWithText(TextButton, '영상 목록'));
    await settle(tester);
    expect(find.text('아직 사건이 없습니다'), findsOneWidget);

    await tester.tap(find.widgetWithText(TextButton, '사건 관계자 연결'));
    await settle(tester);
    expect(find.text('피해자 아이디'), findsOneWidget);
  });

  testWidgets('대기 중이면 진행도와 앞에 N건을 보이고 5초마다 다시 부른다 (2.5)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('queued', extra: {'queue_ahead': 2})),
    });
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('처리를 대기중입니다. 앞에 2건이 있습니다.'), findsOneWidget);
    expect(find.text('사용자 입력 중'), findsOneWidget); // 진행도 4단계
    expect(backend.count('GET /api/videos/7'), 1);

    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(backend.count('GET /api/videos/7'), 2);
    await unmount(tester);
  });

  testWidgets('관리자 계정은 입력 전 stage1_done에서 피해자 입력을 기다린다 (2.5, D-204)', (tester) async {
    final backend = FakeBackend({'GET /api/videos/7': (_) => json(video('stage1_done'))});
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('피해자의 입력을 기다리고 있습니다.'), findsOneWidget);
    expect(backend.calls, isNot(contains('GET /api/videos/7/still')));
    await unmount(tester);
  });

  testWidgets('피해자 계정은 분석이 끝나면 안내에서 멈추고 후보를 부르지 않는다 (2.5, D-204)', (tester) async {
    final backend = FakeBackend({'GET /api/videos/7': (_) => json(video('ready'))}, role: 'victim');
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('분석이 끝났습니다.'), findsOneWidget);
    expect(find.text('영상 상태'), findsOneWidget); // 영상 상태 | 관리자 ○○ | 열람기한 (D-211)
    expect(find.text('2026-11-19 10:00까지 열람 가능'), findsOneWidget);
    expect(find.text('목록으로'), findsNothing); // 상단 메뉴 [영상 목록]으로 간다 (D-211)
    expect(backend.calls, isNot(contains('GET /api/videos/7/batch')));
  });

  testWidgets('피해자 계정은 끝난 영상에 사건 지점 시간이 없으면 분석 완료 안내 (2.5, D-210)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('exhausted')),
      'GET /api/videos/7/incident-times': (_) => json([]),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('분석이 끝났습니다.'), findsOneWidget);
  });

  testWidgets('실패하면 남은 횟수와 [분석 다시 시도], 접수되면 대기 화면 (2.5, D-112)', (tester) async {
    var retried = false;
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(
        retried
            ? video('stage2_running')
            : video('failed', extra: {'error_kind': 'temporary', 'can_retry': true, 'retry_left': 2}),
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
    expect(find.text('영상을 분석하고 있습니다.\n24시간 영상 기준 약 20분 걸립니다.'), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('관리자가 후보 화면에 들어가면 안내창에 체크해야 23번을 부르고 연다 (2.7, D-204)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('ready')),
      'POST /api/videos/7/viewing-agreement': (req) {
        expect(jsonDecode(req.body), {'confirm_supervision': true});
        return json(null, 204);
      },
      'GET /api/videos/7/batch': (_) => candidateBatch1187(),
      'GET /api/videos/7/pin': (_) => json([]),
    });
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('피해자와 함께 열람하고, 함께 고정합니다'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, '동의하고 열람')).onPressed, isNull);
    expect(backend.calls, isNot(contains('GET /api/videos/7/batch')));

    await agreeSupervision(tester);
    expect(backend.calls, contains('POST /api/videos/7/viewing-agreement'));
    expect(find.text('점수: 87'), findsOneWidget);
  });

  testWidgets('확인 끝내기 뒤 결과 화면은 안내창 없이, 목록에서 들어가면 안내창을 띄운다 (2.7, D-226)', (tester) async {
    var ended = false;
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(
        ended ? video('exhausted', extra: {'candidate_total': 1, 'candidate_unavailable': 0}) : video('ready'),
      ),
      'GET /api/videos/7/batch': (_) => json({
        'list': 'main',
        'batch_no': 1,
        'unavailable': 0,
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
        'lists': lists(mainRemaining: 0),
      }),
      'GET /api/videos/7/pin': (_) => json([pinned1187()]),
      'POST /api/videos/7/batch/next': (_) {
        ended = true;
        return json({'status': 'exhausted', 'lists': lists(mainRemaining: 0)});
      },
      'POST /api/videos/7/viewing-agreement': (_) => json(null, 204),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    await tester.tap(find.widgetWithText(FilledButton, '확인 끝내기'));
    await settle(tester);
    await tester.tap(find.widgetWithText(FilledButton, '끝내기'));
    await settle(tester);
    expect(find.text('피해자와 함께 열람하고, 함께 고정합니다'), findsNothing);
    expect(backend.count('POST /api/videos/7/viewing-agreement'), 0);
    expect(find.text('고정 목록'), findsOneWidget);
    await unmount(tester);

    // 영상 목록에서 누른 것처럼 상태 화면부터 들어가면 다시 띄운다
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('피해자와 함께 열람하고, 함께 고정합니다'), findsOneWidget);
    await agreeSupervision(tester);
    expect(backend.count('POST /api/videos/7/viewing-agreement'), 1);
    expect(find.text('고정 목록'), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('안내창에서 [취소]하면 동의를 남기지 않고 목록으로 (2.7)', (tester) async {
    final backend = FakeBackend({'GET /api/videos/7': (_) => json(video('ready')), 'GET /api/videos': (_) => json([])});
    await pumpApp(tester, backend, '/videos/7');
    await tester.tap(find.widgetWithText(OutlinedButton, '취소'));
    await settle(tester);
    expect(backend.calls, isNot(contains('POST /api/videos/7/viewing-agreement')));
    expect(find.text('아직 사건이 없습니다'), findsOneWidget);
  });

  testWidgets('후보 0건으로 끝나면 사건 없음이 아니라 탐지 안 됨으로 쓴다 (2.8)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('exhausted', extra: {'candidate_total': 0, 'candidate_unavailable': 0})),
      'POST /api/videos/7/viewing-agreement': (_) => json(null, 204),
    });
    await pumpApp(tester, backend, '/videos/7');
    await agreeSupervision(tester);
    expect(find.text('후보 구간이 탐지되지 않았습니다'), findsOneWidget);
  });

  testWidgets('위탁계약 체크 3개를 모두 해야 영상 선택으로 넘어간다 (2.4)', (tester) async {
    final backend = FakeBackend({});
    await pumpApp(tester, backend, '/cases/3/upload');
    final agree = find.widgetWithText(FilledButton, '동의하고 영상 선택하기');
    expect(tester.widget<FilledButton>(agree).onPressed, isNull);

    expect(find.text('위탁계약 동의 완료'), findsNothing);
    await agreeUpload(tester);
    expect(find.text('파일 선택'), findsOneWidget);
    expect(find.text('위탁계약 동의 완료'), findsOneWidget); // 영상 올리기 | 피해자 | 위탁계약 동의 완료 (D-211)
    expect(find.textContaining('열람기한'), findsNothing); // 업로드 전에는 열람기한을 보이지 않는다
    expect(backend.screenCalls, isEmpty); // 동의는 따로 저장하지 않는다
  });

  testWidgets('녹화 시작 시각은 달력·시계로 고르면 형식대로 채워진다 (2.4, D-190)', (tester) async {
    final backend = FakeBackend({});
    await pumpApp(tester, backend, '/cases/3/upload');
    await agreeUpload(tester);

    final field = find.byType(TextField);
    expect(tester.widget<TextField>(field).readOnly, isTrue); // 직접 칠 수 없다
    await tester.tap(field);
    await settle(tester);
    expect(find.byIcon(Icons.edit_outlined), findsNothing); // 달력에서 직접 입력으로 바꾸는 버튼 없음
    await tester.tap(find.text('확인')); // 달력: 오늘
    await settle(tester);

    // 시각: 오전 12시 00분 00초에서 오후 9시 05분 03초로 (펼친 목록에 보이는 값만 고른다)
    Future<void> choose(Finder current, String next) async {
      await tester.tap(current);
      await settle(tester);
      await tester.tap(find.text(next).last);
      await settle(tester);
    }

    await choose(find.text('오전'), '오후');
    await choose(find.text('12'), '9');
    await choose(find.text('00').first, '05'); // 분
    await choose(find.text('00').first, '03'); // 초
    await tester.tap(find.text('확인'));
    await settle(tester);

    final now = DateTime.now();
    String two(int n) => n.toString().padLeft(2, '0');
    expect(tester.widget<TextField>(field).controller!.text, '${now.year}-${two(now.month)}-${two(now.day)} 21:05:03');
  });

  testWidgets('업로드가 끝나면 7번을 부르고 그 영상의 상태 화면으로 간다 (2.4)', (tester) async {
    final backend = FakeBackend({
      'POST /api/cases/3/uploads/presign': (req) {
        final body = jsonDecode(req.body);
        expect(body['filename'], 'CH03.mp4');
        expect(body['agreement']['confirm_signage'], isTrue);
        return json({'video_id': 17, 'upload_url': 'http://s3/videos/17/original.mp4'});
      },
      'POST /api/videos/17/upload/complete': (_) => json(null, 204),
      'GET /api/videos/17': (_) => json({
        ...video('queued', extra: {'queue_ahead': 0}),
        'video_id': 17,
      }),
    });
    await pumpApp(tester, backend, '/cases/3/upload', browser: FakeBrowser(file: FakeFile('CH03.mp4', 100)));
    await agreeUpload(tester);
    await tester.tap(find.text('파일 선택'));
    await settle(tester);
    await tester.tap(find.widgetWithText(FilledButton, '업로드'));
    await settle(tester);
    // 상태 화면은 머리의 피해자 이름을 보이려고 8번도 부른다
    expect(
      backend.screenCalls,
      containsAllInOrder([
        'POST /api/cases/3/uploads/presign',
        'POST /api/videos/17/upload/complete',
        'GET /api/videos/17',
      ]),
    );
    expect(find.text('처리를 대기중입니다. 앞에 0건이 있습니다.'), findsOneWidget);
    await unmount(tester);
  });

  testWidgets('업로드가 끊기면 안내를 띄우고 동의 단계로 돌아간다 (2.4)', (tester) async {
    final backend = FakeBackend({
      'POST /api/cases/3/uploads/presign': (_) => json({'video_id': 17, 'upload_url': 'http://s3/x'}),
    });
    await pumpApp(
      tester,
      backend,
      '/cases/3/upload',
      browser: FakeBrowser(file: FakeFile('CH03.mp4', 100), putStatus: 0),
    );
    await agreeUpload(tester);
    await tester.tap(find.text('파일 선택'));
    await settle(tester);
    await tester.tap(find.widgetWithText(FilledButton, '업로드'));
    await settle(tester);
    expect(find.text('업로드가 중단됐습니다. 다시 올려 주세요.'), findsOneWidget);
    expect(find.text('동의하고 영상 선택하기'), findsOneWidget);
    expect(backend.calls, isNot(contains('POST /api/videos/17/upload/complete')));
  });

  testWidgets('[찾음]을 누르면 확정됨 표시와 [확인 끝내기]를 누를 수 있다 (2.7)', (tester) async {
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
      'POST /api/videos/7/pin': (_) => json([pinned1187()]),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    expect(find.text('점수: 87'), findsOneWidget);
    expect(find.text('후보 10'), findsOneWidget);
    expect(find.text('점수 미산출 (0)'), findsOneWidget);
    expect(find.text('2026-11-19 10:00까지 열람 가능'), findsOneWidget); // 제목 위 작은 글자 (캔버스 2.7)
    expect(find.text('이 묶음에 영상을 준비하지 못해 볼 수 없는 후보가 1건 있습니다.'), findsOneWidget);
    expect(find.text('다음 ▶'), findsOneWidget); // 새 묶음을 받는 버튼도 이름은 [다음 ▶] (D-190)
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, '확인 끝내기')).onPressed, isNull); // 늘 보이지만 막힘

    await tester.tap(find.widgetWithText(FilledButton, '찾음'));
    await settle(tester);
    expect(find.byType(AlertDialog), findsNothing); // 확인창 없이 바로 고정 (D-190)
    expect(find.text('확정됨'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, '확인 끝내기')).onPressed, isNotNull);
    expect(backend.calls, contains('POST /api/videos/7/pin'));
  });

  testWidgets('마지막 페이지는 [다음 ▶]이 막히고 [확인 끝내기]로 확인창 뒤 끝낸다 (2.7, D-190)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('ready')),
      'GET /api/videos/7/batch': (_) => json({
        'list': 'main',
        'batch_no': 1,
        'unavailable': 0,
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
        'lists': lists(mainRemaining: 0),
      }),
      'GET /api/videos/7/pin': (_) => json([]),
      'POST /api/videos/7/batch/next': (_) => json({'status': 'exhausted', 'lists': lists(mainRemaining: 0)}),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    expect(tester.widget<OutlinedButton>(find.widgetWithText(OutlinedButton, '다음 ▶')).onPressed, isNull);

    await tester.tap(find.widgetWithText(FilledButton, '확인 끝내기')); // 고정이 없어도 보인다
    await settle(tester);
    expect(find.text('후보 확인을 끝낼까요?'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, '끝내기'));
    await settle(tester);
    expect(backend.calls, contains('POST /api/videos/7/batch/next'));
    await unmount(tester);
  });

  testWidgets('전부 열람 불가로 두 탭이 끝났으면 [다음 ▶]으로 확인창 뒤 끝낸다 (2.7, D-203)', (tester) async {
    final done = {
      'main': {'latest_batch_no': 1, 'remaining': 0, 'done': true, 'unavailable': 3},
      'parse_failed': {'latest_batch_no': null, 'remaining': 0, 'done': true, 'unavailable': 0},
    };
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('ready')),
      'GET /api/videos/7/batch': (_) => json({
        'list': 'main',
        'batch_no': 1,
        'unavailable': 3,
        'candidates': [],
        'lists': done,
      }),
      'GET /api/videos/7/pin': (_) => json([]),
      'POST /api/videos/7/batch/next': (_) => json({'status': 'exhausted', 'lists': done}),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, '확인 끝내기')).onPressed, isNull);

    await tester.tap(find.widgetWithText(OutlinedButton, '다음 ▶'));
    await settle(tester);
    expect(find.textContaining('마지막 묶음입니다.'), findsOneWidget);
    expect(backend.calls, isNot(contains('POST /api/videos/7/batch/next')));
    await tester.tap(find.widgetWithText(FilledButton, '넘기기'));
    await settle(tester);
    expect(backend.calls, contains('POST /api/videos/7/batch/next'));
    await unmount(tester);
  });

  testWidgets('[고정 해제]로 풀면 확정됨과 [확인 끝내기]가 막히고 [찾음]이 돌아온다 (2.7, D-189)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('ready')),
      'GET /api/videos/7/batch': (_) => candidateBatch1187(),
      'GET /api/videos/7/pin': (_) => json([pinned1187()]),
      'DELETE /api/videos/7/pin/1187': (_) => json([]),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    expect(find.text('확정됨'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, '확인 끝내기')).onPressed, isNotNull);
    expect(find.widgetWithText(FilledButton, '찾음'), findsNothing);

    await tester.tap(find.widgetWithText(OutlinedButton, '고정 해제'));
    await settle(tester);
    expect(find.byType(AlertDialog), findsNothing); // 확인창 없이 바로 해제 (D-190)
    expect(backend.calls, contains('DELETE /api/videos/7/pin/1187'));
    expect(find.text('확정됨'), findsNothing);
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, '확인 끝내기')).onPressed, isNull); // 늘 보이지만 막힘
    expect(find.widgetWithText(FilledButton, '찾음'), findsOneWidget);
  });

  testWidgets('다른 탭에서 이미 끝냈으면 해제가 INVALID_STATE로 거절되고 상태를 다시 읽는다 (2.7, D-189)', (tester) async {
    var finished = false; // 화면을 연 뒤 다른 탭에서 [확인 끝내기]를 눌렀다고 본다
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video(finished ? 'finished' : 'ready')),
      'GET /api/videos/7/batch': (_) => candidateBatch1187(),
      'GET /api/videos/7/pin': (_) => json([pinned1187()]),
      'DELETE /api/videos/7/pin/1187': (_) {
        finished = true;
        return apiError(409, 'INVALID_STATE');
      },
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    final before = backend.count('GET /api/videos/7');

    await tester.tap(find.widgetWithText(OutlinedButton, '고정 해제'));
    await settle(tester);
    expect(backend.count('GET /api/videos/7'), greaterThan(before));
    // 결과 화면으로 다시 들어가므로 해제 확인창이 아니라 관리·감독 안내창이 뜬다 (2.7)
    expect(find.text('피해자와 함께 열람하고, 함께 고정합니다'), findsOneWidget);
  });

  testWidgets('결과 화면은 원본 기준 시간과 추정 실제 시각을 보인다 (2.9)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('finished')),
      'GET /api/videos/7/pin': (_) => json([pinnedWithTime(clipUrl: 'http://x/1187.mp4')]),
    });
    await pumpApp(tester, backend, '/videos/7/results');
    expect(find.text('03:40:35 ~ 03:41:05'), findsOneWidget);
    expect(find.text('2026-09-17 03:40:35 ~ 03:41:05 (관리자 입력 기준 추정)'), findsOneWidget);
    expect(find.text('2026-11-19 10:00까지 열람 가능'), findsOneWidget);
  });

  testWidgets('피해자 계정 결과 화면은 클립 없이 고정한 시각만 보인다 (2.9, D-211)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('finished')),
      // 25번에는 재생 URL과 후보 번호가 없다 (D-210)
      'GET /api/videos/7/incident-times': (_) => json([
        {...pinnedWithTime(clipUrl: null)}
          ..remove('clip_url')
          ..remove('candidate_clip_id'),
      ]),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos/7');
    expect(find.text('03:40:35 ~ 03:41:05'), findsOneWidget);
    expect(find.textContaining('고정된 장면의 시각만 볼 수 있습니다.'), findsOneWidget);
    expect(backend.calls, isNot(contains('POST /api/videos/7/viewing-agreement')));
    expect(backend.calls, isNot(contains('GET /api/videos/7/pin')));
  });

  testWidgets('열람기한이 지나 MASKED_EXPIRED를 받으면 보관 기간 종료 안내로 간다 (2.10)', (tester) async {
    // 파기 작업이 돌기 전이라 9번은 아직 masked_deleted가 false다
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('ready')),
      'GET /api/videos/7/batch': (_) => apiError(409, 'MASKED_EXPIRED'),
      'GET /api/videos/7/pin': (_) => apiError(409, 'MASKED_EXPIRED'),
    });
    await pumpApp(tester, backend, '/videos/7/candidates');
    expect(find.text('업로드 완료 후 30일이 지나 보관 기간이 끝났습니다. 만료된 영상은 주기적으로 삭제합니다.'), findsOneWidget);
    expect(find.text('2026-11-19 열람 기한 종료'), findsOneWidget);
  });

  testWidgets('입력을 마친 영상은 입력 화면을 열지 않는다 (2.6, D-66)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('stage1_done', extra: {'input_done': true, 'queue_ahead': 0})),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos/7/input');
    expect(find.textContaining('입력을 저장했습니다.'), findsOneWidget);
    expect(backend.calls, isNot(contains('GET /api/videos/7/still')));
    await unmount(tester);
  });

  testWidgets('앞쪽 변을 눌러야 [다음]이 켜지고, 저장 본문은 형식 6에 front_edge를 싣는다 (2.6, D-208, D-212)', (tester) async {
    Map<String, dynamic>? saved;
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('stage1_done')),
      'GET /api/videos/7/still': (_) => json({
        'still_frame_id': 305,
        't_sec': 0.0,
        'image_url': 'http://x/0.jpg',
        'detections': [
          {
            'det_id': 1,
            'bbox': [400, 300, 1200, 800],
            'polygon': [[400, 300], [1200, 300], [1200, 800], [400, 800]],
          },
        ],
      }),
      'PUT /api/videos/7/input': (req) {
        saved = jsonDecode(req.body) as Map<String, dynamic>;
        return json({'video_id': 7, 'status': 'queued', 'input_done': true});
      },
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos/7/input');

    // 정지 장면(원본 1920×1080) 위 원본 좌표를 화면 좌표로 바꾼다
    final still = tester.getRect(
      find.descendant(of: find.byType(StillCanvas), matching: find.byType(GestureDetector)).first,
    );
    final scale = still.width / 1920;
    Offset at(double x, double y) => still.topLeft + Offset(x * scale, y * scale);
    final next = find.widgetWithText(FilledButton, '다음');
    Future<void> tapNext() async {
      await tester.tap(next);
      await tester.pump();
    }

    await tester.tapAt(at(800, 500)); // ① 차량
    await tester.pump();
    await tapNext();
    await tester.tap(find.widgetWithText(OutlinedButton, '보임')); // ②
    await tester.pump();
    await tapNext();
    await tester.dragFrom(at(300, 400), Offset(300 * scale, 200 * scale)); // ③ 차량 bbox 왼쪽 밖에서 시작 (D-231)
    await tester.pump();
    await tapNext();
    for (final (x, y) in const [(450.0, 600.0), (1150.0, 600.0), (1150.0, 790.0), (450.0, 790.0)]) {
      await tester.tapAt(at(x, y)); // ④ 네 모서리
      await tester.pump();
    }
    await tapNext();

    // ⑤ 고르기 전에는 [다음]이 막힌다
    expect(find.text('차의 앞쪽 변을 눌러주세요'), findsOneWidget);
    expect(tester.widget<FilledButton>(next).onPressed, isNull);
    await tester.tapAt(at(800, 790)); // 변 2 (점 3 → 점 4)
    await tester.pump();
    expect(find.text('앞쪽 변을 골랐습니다.'), findsOneWidget);
    expect(tester.widget<FilledButton>(next).onPressed, isNotNull);
    await tapNext();

    await tester.tapAt(at(800, 600)); // ⑥ 파손 변 0
    await tester.pump();
    await tapNext();
    await tapNext(); // ⑦ 사진·설명 없이
    expect(find.text('파란 선'), findsOneWidget); // ⑧ 확인표

    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await tester.pump();
    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.widgetWithText(FilledButton, '저장')));
    await settle(tester);

    expect(saved?['schema_version'], 6);
    expect(saved?['damage']['front_edge'], 2);
    expect(saved?['damage']['damage_edges'], [0]);
    expect((saved?['damage']['damage_bbox'] as List)[0], lessThan(400)); // 차량 밖도 받는다 (D-231)
    expect(saved?['vehicle'], {'det_id': 1}); // polygon은 보내지 않는다 (D-221)
    await unmount(tester);
  });

  testWidgets('차 안쪽을 누르면 [다음]이 켜지고, bbox 안이어도 polygon 밖을 누르면 풀린다 (2.6, D-221)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('stage1_done')),
      'GET /api/videos/7/still': (_) => json({
        'still_frame_id': 305,
        't_sec': 0.0,
        'image_url': 'http://x/0.jpg',
        'detections': [
          {
            'det_id': 1,
            'bbox': [400, 300, 1200, 800],
            'polygon': [[400, 300], [1200, 300], [400, 800]], // 삼각형: 오른쪽 아래는 bbox 안이지만 차 밖
          },
        ],
      }),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos/7/input');

    final still = tester.getRect(
      find.descendant(of: find.byType(StillCanvas), matching: find.byType(GestureDetector)).first,
    );
    final scale = still.width / 1920;
    Offset at(double x, double y) => still.topLeft + Offset(x * scale, y * scale);
    final next = find.widgetWithText(FilledButton, '다음');

    expect(tester.widget<FilledButton>(next).onPressed, isNull);
    await tester.tapAt(at(500, 400)); // 차 안쪽
    await tester.pump();
    expect(tester.widget<FilledButton>(next).onPressed, isNotNull);

    await tester.tapAt(at(1100, 700)); // bbox 안, polygon 밖
    await tester.pump();
    expect(tester.widget<FilledButton>(next).onPressed, isNull);
    await unmount(tester);
  });

  testWidgets('탐지 0건이면 관리자에게 다시 올려 달라는 안내 (2.6, D-65)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos/7': (_) => json(video('stage1_done')),
      'GET /api/videos/7/still': (_) =>
          json({'still_frame_id': 305, 't_sec': 0.0, 'image_url': 'http://x/0.jpg', 'detections': []}),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos/7/input');
    expect(find.textContaining('이 장면에서 본인 차량을 찾지 못했습니다.'), findsOneWidget);
    expect(find.textContaining('같은 사건에 올려 달라고'), findsOneWidget);
  });
}

Map<String, dynamic> pinned1187() => {
  'candidate_clip_id': 1187,
  'start_sec': 13235.0,
  'end_sec': 13265.0,
  'est_start_at': null,
  'est_end_at': null,
  'clip_url': 'http://x/1187.mp4',
  'pinned_at': '2026-10-20T15:20:11+09:00',
};

Map<String, dynamic> pinnedWithTime({required String? clipUrl}) => {
  'candidate_clip_id': 1187,
  'start_sec': 13235.0,
  'end_sec': 13265.0,
  'est_start_at': '2026-09-17T03:40:35+09:00',
  'est_end_at': '2026-09-17T03:41:05+09:00',
  'clip_url': clipUrl,
  'pinned_at': '2026-10-20T15:20:11+09:00',
};

http.Response candidateBatch1187() => json({
  'list': 'main',
  'batch_no': 1,
  'unavailable': 0,
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
});
