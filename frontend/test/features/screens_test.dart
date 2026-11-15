import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:parking_lot_frontend/core/api/chat_socket.dart';
import 'package:parking_lot_frontend/core/constants.dart';
import 'package:parking_lot_frontend/core/models/message.dart';
import 'package:parking_lot_frontend/core/settings.dart';
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

/// 29·30·31번의 메시지 한 건 (05장 5.12).
Map<String, Object?> chatMsg(int id, String body, {required bool mine, String at = '2026-11-02T11:00:00+09:00'}) => {
  'id': id,
  'mine': mine,
  'body': body,
  'created_at': at,
};

/// 29번의 대화 상대 한 줄.
Map<String, Object?> chatPeer(int userId, String name, {Map<String, Object?>? last, int unread = 0}) => {
  'peer_user_id': userId,
  'peer_name': name,
  'last_message': last,
  'unread': unread,
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
  testWidgets('로그인하지 않았으면 로그인 화면, 로그인하면 이용 안내 → 사건 목록 (2.1, 2.13, D-235, D-237)', (tester) async {
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
    expect(find.text('Info.'), findsWidgets);
    expect(find.text('관리자 계정 사용법'), findsOneWidget);
    await tester.tap(find.text('사건 목록'));
    await settle(tester);
    expect(find.text('사건 1건'), findsOneWidget);
    expect(find.text('CH01.mp4'), findsOneWidget); // 사건 이름이 없으면 파일 이름 (D-237)
    expect(find.text('victim02'), findsOneWidget); // 피해자 칸 (22번)
    expect(find.text('후보 선택 가능'), findsOneWidget);
    expect(find.text('2026-10-20'), findsNothing); // 업로드 날짜 칸은 없앴다 (D-237)
    expect(find.text('새로고침'), findsNothing);
    expect(find.text('2026-11-19'), findsOneWidget); // 열람기한은 날짜만 (D-190)
    expect(find.text('관리자 계정'), findsOneWidget);
  });

  testWidgets('목록은 업로드 날짜 최신순이고 표 머리를 눌러도 정렬되지 않는다 (2.2, D-241)', (tester) async {
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

    expect(order(), ['A', 'B', 'C', 'D', 'E', 'F', 'G']); // 업로드 날짜 최신순
    expect(find.text('확인 완료'), findsNWidgets(2)); // finished·exhausted 같은 이름
    expect(find.text('종료됨'), findsOneWidget);

    await tester.tap(find.text('상태'), warnIfMissed: false);
    await settle(tester);
    expect(order(), ['A', 'B', 'C', 'D', 'E', 'F', 'G']); // 정렬 버튼이 없다
    expect(find.byIcon(Icons.unfold_more), findsNothing);

    expect(backend.count('GET /api/videos'), 2); // 목록 1번 + 관리자 [알림] 배지 1번 (D-243)
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
      expect(find.textContaining('2026-11-19'), findsNWidgets(2), reason: '폭 $width'); // 접어도 열람기한은 보인다
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
    expect(find.text('—'), findsOneWidget); // 사건 이름도 영상도 없다 (캔버스, D-237)
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
    expect(find.text('사건 1건'), findsOneWidget); // 제목은 줄 수다
    expect(find.text('업로드 중'), findsOneWidget);
    expect(find.text('parking_admin'), findsOneWidget);

    await tester.tap(find.text('업로드 중'));
    await settle(tester);
    expect(find.text('CCTV 영상 올리기'), findsNothing);
    expect(find.text('업로드 중'), findsOneWidget);
  });

  testWidgets('피해자는 알림에서 초대를 수락하면 그 사건 영상이 목록에 보인다 (2.11, D-233)', (tester) async {
    var accepted = false;
    final backend = FakeBackend({
      // 서버가 아직 수락 전 영상을 주더라도 화면이 거르는지 함께 본다
      'GET /api/videos': (_) => json([video('stage1_done')]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': accepted ? '2026-11-10T10:00:00+09:00' : null},
        ],
      }),
      'POST /api/cases/3/accept': (_) {
        accepted = true;
        return json(null, 204);
      },
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos');
    expect(find.text('CH01.mp4'), findsNothing);
    expect(find.text('1'), findsOneWidget); // [알림] 배지

    await tester.tap(find.text('채팅'));
    await settle(tester);
    expect(find.text('연결 요청이 왔어요!'), findsOneWidget);
    expect(find.text('거절'), findsNothing); // 거절은 없다 (D-233)
    expect(find.text('내 차량을 입력해 주세요!'), findsNothing); // 수락 전에는 영상 알림이 없다
    await tester.tap(find.widgetWithText(FilledButton, '수락'));
    await settle(tester);
    expect(backend.count('POST /api/cases/3/accept'), 1);
    expect(find.text('사건을 수락했습니다. 사건 목록에서 볼 수 있습니다.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '수락'), findsNothing);
    expect(find.text('연결을 수락했어요!'), findsOneWidget);
    expect(find.text('내 차량을 입력해 주세요!'), findsOneWidget); // 수락하면 영상 상태 알림이 붙는다 (D-237)
    expect(find.widgetWithText(FilledButton, '차량 입력'), findsOneWidget); // 할 일은 카드가 아니라 버튼으로 (D-304)
    // 피해자 기준: 관리자가 보낸 요청·영상 알림은 왼쪽, 내가 한 수락은 오른쪽 (D-297)
    final middle = tester.view.physicalSize.width / tester.view.devicePixelRatio / 2;
    final talkLeft = tester.getTopLeft(find.text('연결 요청이 왔어요!')).dx;
    expect(tester.getTopLeft(find.text('연결을 수락했어요!')).dx, greaterThan(middle));
    expect(tester.getTopLeft(find.text('내 차량을 입력해 주세요!')).dx, talkLeft);
    expect(talkLeft, lessThan(tester.getTopLeft(find.text('연결을 수락했어요!')).dx));

    await tester.tap(find.text('사건 목록'));
    await settle(tester);
    expect(find.text('CH01.mp4'), findsOneWidget);
    expect(find.text('1'), findsNothing);
  });

  testWidgets('수락 전 사건은 피해자 목록에 없고, 관리자 목록에는 "수락 대기 중"이다 (2.2, D-233)', (tester) async {
    Map<String, http.Response Function(http.Request)> routes() => {
      'GET /api/videos': (_) => json([video('stage1_done')]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': null},
        ],
      }),
    };
    await pumpApp(tester, FakeBackend(routes(), role: 'victim'), '/videos');
    expect(find.text('CH01.mp4'), findsNothing);
    expect(find.text('수락 대기 중'), findsNothing);
    expect(find.text('아직 올라온 영상이 없습니다'), findsOneWidget);
    await unmount(tester);

    await pumpApp(tester, FakeBackend(routes()), '/videos');
    expect(find.text('CH01.mp4'), findsOneWidget);
    expect(find.text('수락 대기 중'), findsOneWidget);
    expect(find.text('사전 입력 필요'), findsNothing);
  });

  testWidgets('관리자 알림은 수락·후보 선택 가능·분석 실패를 보이고 [수락] 버튼이 없다. 상태 화면은 카드가 아니라 버튼으로 간다 (2.11, D-243, D-304)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([
        video('ready'),
        video('failed', extra: {'video_id': 8, 'original_filename': 'CH02.mp4'}),
      ]),
      'GET /api/videos/7': (_) => json(video('ready')),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': '2026-11-10T10:00:00+09:00'},
        ],
      }),
    });
    await pumpApp(tester, backend, '/videos');
    expect(find.text('2'), findsOneWidget); // [알림] 배지: 후보 선택 가능 1 + 분석 실패 1
    await tester.tap(find.text('채팅'));
    await settle(tester);
    expect(find.text('연결을 요청했어요'), findsOneWidget);
    expect(find.text('연결이 수락되었어요!'), findsOneWidget);
    expect(find.text('후보를 고를 수 있어요!'), findsOneWidget);
    expect(find.text('영상 분석에 실패했어요'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '수락'), findsNothing);

    await tester.tap(find.text('후보를 고를 수 있어요!'));
    await settle(tester);
    expect(backend.count('GET /api/videos/7'), 0); // 카드는 눌러도 넘어가지 않는다 (D-304)

    await tester.tap(find.widgetWithText(FilledButton, '후보 선택'));
    await settle(tester);
    expect(backend.count('GET /api/videos/7'), greaterThan(0)); // 버튼을 누르면 그 영상의 상태 화면
  });

  testWidgets('관리자 채팅은 피해자별로 묶고, 같은 피해자의 사건은 한 대화에 잇는다 (2.11)', (tester) async {
    final first = chatMsg(1, '언제 올라오나요?', mine: false);
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'case_name': '첫 사건', 'accepted_at': '2026-11-02T10:00:00+09:00'},
          {...case3(), 'id': 4, 'case_name': '둘째 사건', 'created_at': '2026-11-05T09:00:00+09:00', 'accepted_at': null},
          {...case3(), 'id': 5, 'victim_name': 'victim03', 'created_at': '2026-11-03T09:00:00+09:00', 'accepted_at': null},
        ],
      }),
      // 22번에는 상대 계정 ID가 없어 이름으로 29번과 짝짓는다 (D-303). victim03은 수락한 사건이 없어 29번에 없다
      'GET /api/chats': (_) => json({
        'items': [chatPeer(12, 'victim02', last: first)],
        'unread_total': 0,
      }),
      'GET /api/chats/12/messages': (_) => json({'items': [first], 'has_more': false}),
      'PUT /api/chats/12/read': (_) => json(null, 204),
    });
    await pumpApp(tester, backend, '/notifications');
    expect(find.text('victim03'), findsOneWidget);
    expect(find.text('victim02'), findsNWidgets(2)); // 왼쪽 한 줄 + 오른쪽 대화 제목 (최근 사람이 먼저)
    // 목록 요약은 "가장 최근 알림 · 가장 최근 채팅", 채팅이 없으면 알림만 (D-297)
    expect(find.text('연결 요청 · 언제 올라오나요?'), findsOneWidget);
    expect(find.text('언제 올라오나요?'), findsOneWidget); // 30번 메시지가 대화에 보인다
    expect(find.text('연결 요청'), findsOneWidget);
    expect(find.text('2026-11-01'), findsOneWidget); // 사건 구분선은 날짜만
    expect(find.text('2026-11-05'), findsOneWidget);
    expect(find.text('첫 사건'), findsNWidgets(2)); // 연결 요청·연결 수락 카드의 작은 글씨는 사건 이름만
    expect(find.text('수락 대기 중'), findsNothing);
    expect(backend.count('PUT /api/chats/12/read'), 1); // 그린 뒤 읽음으로 알린다

    await tester.tap(find.text('victim03'));
    await settle(tester);
    expect(find.text('첫 사건'), findsNothing);
    expect(find.text('연결을 요청했어요'), findsOneWidget);
    expect(find.text('사건을 수락하면 메시지를 보낼 수 있습니다.'), findsOneWidget); // 29번에 없는 상대
    expect(backend.screenCalls.where((c) => c.contains('/api/chats/') && c.contains('/messages')).length, 1);
  });

  testWidgets('채팅은 기존 메시지를 좌우로 나눠 보이고, 보내면 31번 뒤 29번을 다시 읽는다 (2.11, D-303)', (tester) async {
    final messages = <Map<String, Object?>>[chatMsg(1, '영상을 올렸습니다', mine: false, at: '2026-11-02T10:00:00+09:00')];
    Object? readBody;
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': '2026-11-02T09:00:00+09:00'},
        ],
      }),
      'GET /api/chats': (_) => json({
        'items': [chatPeer(1, 'parking_admin', last: messages.last)],
        'unread_total': 0,
      }),
      'GET /api/chats/1/messages': (_) => json({'items': messages, 'has_more': false}),
      'POST /api/chats/1/messages': (req) {
        final m = chatMsg(2, (jsonDecode(req.body) as Map)['body'] as String, mine: true, at: '2026-11-02T10:05:00+09:00');
        messages.add(m);
        return json(m, 201);
      },
      'PUT /api/chats/1/read': (req) {
        readBody = jsonDecode(req.body);
        return json(null, 204);
      },
    }, role: 'victim');
    await pumpApp(tester, backend, '/notifications');
    expect(find.text('영상을 올렸습니다'), findsOneWidget);
    // 상대 말풍선은 왼쪽에 있다
    expect(tester.getTopLeft(find.text('영상을 올렸습니다')).dx, lessThan(tester.view.physicalSize.width / 2));
    expect(readBody, {'last_read_message_id': 1}); // 보인 메시지 중 가장 큰 id

    final peersBefore = backend.count('GET /api/chats');
    await tester.enterText(find.byType(TextField), '확인했습니다');
    await tester.tap(find.widgetWithText(FilledButton, '보내기'));
    await settle(tester);
    expect(backend.count('POST /api/chats/1/messages'), 1);
    expect(backend.count('GET /api/chats'), greaterThan(peersBefore));
    expect(find.text('확인했습니다'), findsOneWidget);
    // 내 말풍선은 오른쪽에 있다
    expect(tester.getTopLeft(find.text('확인했습니다')).dx, greaterThan(tester.view.physicalSize.width / 2));
  });

  testWidgets('안 읽은 수는 목록 줄 숫자와 합친 메뉴 배지로 보이고, 대화를 열면 읽음 처리로 사라진다. 30일 안내가 목록 위에 있다 (2.11, D-303)', (tester) async {
    var unread02 = 2; // 처음 열리는 대화. 32번을 부르면 0이 된다
    var unread03 = 3;
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': '2026-11-02T10:00:00+09:00'},
          {...case3(), 'id': 5, 'victim_name': 'victim03', 'created_at': '2026-10-20T09:00:00+09:00', 'accepted_at': '2026-10-20T10:00:00+09:00'},
        ],
      }),
      'GET /api/chats': (_) => json({
        'items': [
          chatPeer(12, 'victim02', last: chatMsg(2, '둘째 메시지', mine: false), unread: unread02),
          chatPeer(13, 'victim03', last: chatMsg(5, '셋째 사람 메시지', mine: false), unread: unread03),
        ],
        'unread_total': unread02 + unread03,
      }),
      'GET /api/chats/12/messages': (_) => json({
        'items': [chatMsg(1, '첫 메시지', mine: false), chatMsg(2, '둘째 메시지', mine: false)],
        'has_more': false,
      }),
      'GET /api/chats/13/messages': (_) => json({'items': [chatMsg(5, '셋째 사람 메시지', mine: false)], 'has_more': false}),
      'PUT /api/chats/12/read': (_) {
        unread02 = 0;
        return json(null, 204);
      },
      'PUT /api/chats/13/read': (_) {
        unread03 = 0;
        return json(null, 204);
      },
    });
    await pumpApp(tester, backend, '/notifications');
    expect(find.text('메시지는 보낸 지 30일이 지나면 지워집니다.'), findsOneWidget);
    expect(backend.count('PUT /api/chats/12/read'), 1); // 처음 고른 사람은 그린 뒤 바로 읽음 처리
    // 고른 사람 숫자는 사라지고, 안 읽은 victim03의 숫자 3이 목록 줄과 메뉴 배지(기존 수 0 + 3)에 하나씩 보인다
    expect(find.text('3'), findsNWidgets(2));
    expect(find.text('2'), findsNothing);

    await tester.tap(find.text('victim03'));
    await settle(tester);
    expect(backend.count('PUT /api/chats/13/read'), 1);
    expect(find.text('3'), findsNothing); // 읽으면 목록 숫자와 메뉴 배지가 함께 사라진다
  });

  testWidgets('33번으로 온 새 메시지는 고른 상대면 대화에 붙고 읽음 처리, 다른 상대면 29번을 다시 읽는다. 같은 id는 버리고 화면을 떠나면 닫는다 (2.11, D-303)', (tester) async {
    var unread03 = 0;
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': '2026-11-02T10:00:00+09:00'},
          {...case3(), 'id': 5, 'victim_name': 'victim03', 'created_at': '2026-10-20T09:00:00+09:00', 'accepted_at': '2026-10-20T10:00:00+09:00'},
        ],
      }),
      'GET /api/chats': (_) => json({
        'items': [
          chatPeer(12, 'victim02', last: chatMsg(1, '첫 메시지', mine: false)),
          chatPeer(13, 'victim03', last: chatMsg(5, '셋째 사람 메시지', mine: false), unread: unread03),
        ],
        'unread_total': unread03,
      }),
      'GET /api/chats/12/messages': (_) => json({'items': [chatMsg(1, '첫 메시지', mine: false)], 'has_more': false}),
      'PUT /api/chats/12/read': (_) => json(null, 204),
    });
    final sockets = FakeChatSockets();
    await pumpApp(tester, backend, '/notifications', sockets: sockets);
    expect(sockets.opened.length, 1); // 화면을 열 때 연결 한 번
    final socket = sockets.opened.single;
    expect(backend.count('PUT /api/chats/12/read'), 1);

    // 지금 고른 victim02의 새 메시지: 대화에 붙고 가장 큰 id(2)로 다시 읽음 처리
    final incoming = ChatMessage.fromJson(chatMsg(2, '새로 온 메시지', mine: false));
    socket.emit(ChatMessageEvent(12, incoming));
    await settle(tester);
    expect(find.text('새로 온 메시지'), findsOneWidget);
    expect(backend.count('PUT /api/chats/12/read'), 2);

    // 같은 id가 또 오면 버린다(말풍선도 읽음 처리도 늘지 않는다)
    socket.emit(ChatMessageEvent(12, incoming));
    await settle(tester);
    expect(find.text('새로 온 메시지'), findsOneWidget);
    expect(backend.count('PUT /api/chats/12/read'), 2);

    // 고르지 않은 victim03의 새 메시지: 대화를 읽지 않고 29번만 다시 읽어 목록 숫자가 늘어난다
    unread03 = 1;
    final peersBefore = backend.count('GET /api/chats');
    socket.emit(ChatMessageEvent(13, ChatMessage.fromJson(chatMsg(6, '다른 상대 메시지', mine: false))));
    await settle(tester);
    expect(backend.count('GET /api/chats'), greaterThan(peersBefore));
    expect(backend.count('GET /api/chats/13/messages'), 0);
    expect(find.text('1'), findsWidgets);

    // 모르는 type의 줄은 이벤트가 되지 않는다
    expect(parseChatEvent('{"type":"typing","peer_user_id":12}'), isNull);
    expect(socket.closed, isFalse);
    await unmount(tester);
    expect(socket.closed, isTrue); // 화면을 떠나면 닫는다
  });

  testWidgets('33번이 그 밖의 이유로 끊기면 다시 연결해 빠진 메시지를 채우고, 4408이면 안내만 하고 다시 연결하지 않는다. 다른 메뉴로 가면 닫는다 (2.11, D-303)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': '2026-11-02T10:00:00+09:00'},
        ],
      }),
      'GET /api/chats': (_) => json({
        'items': [chatPeer(12, 'victim02', last: chatMsg(1, '첫 메시지', mine: false))],
        'unread_total': 0,
      }),
      'GET /api/chats/12/messages': (req) => json({
        // 끊겨 있는 동안 상대가 id 2를 보냈다. after_id=1이면 그것만 온다
        'items': req.url.queryParameters['after_id'] == '1'
            ? [chatMsg(2, '끊긴 동안 온 메시지', mine: false)]
            : [chatMsg(1, '첫 메시지', mine: false)],
        'has_more': false,
      }),
      'PUT /api/chats/12/read': (_) => json(null, 204),
    });
    final sockets = FakeChatSockets();
    await pumpApp(tester, backend, '/notifications', sockets: sockets);
    expect(sockets.opened.length, 1);

    sockets.opened[0].emit(ChatClosedEvent(1006)); // 네트워크 끊김
    await tester.pump(pollInterval - const Duration(seconds: 1));
    expect(sockets.opened.length, 1); // 아직 기다린다
    await tester.pump(const Duration(seconds: 1));
    await settle(tester);
    expect(sockets.opened.length, 2); // pollInterval 뒤 다시 연결
    expect(backend.count('GET /api/chats/12/messages?after_id=1'), 1); // 마지막으로 받은 id 뒤부터 채운다
    expect(find.text('끊긴 동안 온 메시지'), findsOneWidget);
    expect(backend.count('PUT /api/chats/12/read'), 2); // 채운 메시지도 읽음 처리

    sockets.opened[1].emit(ChatClosedEvent(chatCloseTooMany));
    await settle(tester);
    expect(find.textContaining('다른 창에서 채팅을 열어'), findsOneWidget);
    await tester.pump(pollInterval * 2);
    await settle(tester);
    expect(sockets.opened.length, 2); // 4408은 다시 연결하지 않는다

    await tester.tap(find.text('사건 목록'));
    await settle(tester);
    expect(sockets.opened[1].closed, isTrue); // 채팅을 떠나면 닫는다
  });

  testWidgets('메시지가 많아도 입력칸은 화면 아래에 고정되어 보인다 (2.11, D-297)', (tester) async {
    final all = [for (var i = 1; i <= 40; i++) chatMsg(i, '메시지 $i', mine: false, at: '2026-11-02T10:00:00+09:00')];
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': '2026-11-02T09:00:00+09:00'},
        ],
      }),
      'GET /api/chats': (_) => json({
        'items': [chatPeer(1, 'parking_admin', last: all.last)],
        'unread_total': 0,
      }),
      'GET /api/chats/1/messages': (_) => json({'items': all, 'has_more': true}),
      'PUT /api/chats/1/read': (_) => json(null, 204),
    }, role: 'victim');
    await pumpApp(tester, backend, '/notifications');
    final screenHeight = tester.view.physicalSize.height / tester.view.devicePixelRatio;
    final field = tester.getRect(find.byType(TextField));
    expect(field.bottom, lessThanOrEqualTo(screenHeight)); // 화면 안에 있다
    expect(field.bottom, greaterThan(screenHeight - 120)); // 화면 맨 아래 쪽이다
    expect(find.text('메시지 40'), findsOneWidget); // 처음부터 최근 메시지가 보인다
    expect(tester.getRect(find.text('메시지 40')).bottom, lessThan(field.top));
  });

  testWidgets('수락한 사건이 없으면 입력칸 대신 안내를 보인다 (2.11, D-297)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'accepted_at': null},
        ],
      }),
    }, role: 'victim');
    await pumpApp(tester, backend, '/notifications');
    expect(find.text('사건을 수락하면 메시지를 보낼 수 있습니다.'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('관리자 메뉴 5개는 글자 [크게]에서도 상단 바가 넘치지 않는다 (3.8, D-236, D-243, D-291)', (tester) async {
    final browser = FakeBrowser()..local[textSizeStorageKey] = 'large';
    await pumpApp(tester, FakeBackend({}), '/notifications', browser: browser);
    for (final width in [1000.0, 1200.0, 1400.0, 999.0, 800.0]) {
      tester.view.physicalSize = Size(width, 1000);
      await settle(tester);
      expect(tester.takeException(), isNull, reason: '폭 $width');
    }
  });

  testWidgets('설정은 내 계정·보안 설정·환경 설정·서비스를 보이고, 로그아웃·글자 크기 말고는 안내 창만 띄운다 (D-291)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([video('stage1_done')]),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos');
    // 상단 바에는 [로그아웃]·[마이페이지]·[환경설정]이 없고 [설정] 하나다
    expect(find.text('로그아웃'), findsNothing);
    expect(find.text('마이페이지'), findsNothing);
    expect(find.text('환경설정'), findsNothing);
    await tester.tap(find.text('설정'));
    await settle(tester);
    for (final title in ['내 계정', '보안 설정', '환경 설정', '서비스', '닉네임', '계정 유형', '비밀번호', '화면 모드', '글자 크기']) {
      expect(find.text(title), findsOneWidget, reason: title);
    }
    expect(find.text('victim02'), findsOneWidget);
    expect(find.text('사건 관계자'), findsOneWidget);
    // 화면 모드는 [라이트]로 표시만 한다
    RadioGroup<String> mode() => tester.widget(find.byType(RadioGroup<String>));
    expect(mode().groupValue, 'light');

    for (final (label, button) in [
      ('닉네임 변경', find.byTooltip('닉네임 변경')),
      ('비밀번호 변경', find.widgetWithText(OutlinedButton, '비밀번호 변경')),
      ('계정 삭제', find.widgetWithText(OutlinedButton, '계정 삭제')),
      ('다크 모드', find.text('다크')),
      ('1:1 문의', find.text('1:1 문의')),
      ('공지사항', find.text('공지사항')),
      ('이용약관', find.text('이용약관')),
    ]) {
      await tester.ensureVisible(button);
      await tester.tap(button);
      await settle(tester);
      expect(find.text('준비 중인 기능입니다'), findsOneWidget, reason: label);
      expect(find.text('[$label]은(는) 아직 사용할 수 없습니다.'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, '확인'));
      await settle(tester);
      expect(find.text('준비 중인 기능입니다'), findsNothing);
    }
    expect(mode().groupValue, 'light'); // [다크]를 눌러도 바뀌지 않는다
    // 서버에는 읽기만 했고, 바꾸는 호출은 없다
    expect(backend.calls.where((c) => !c.startsWith('GET ')), isEmpty);
  });

  testWidgets('설정의 [로그아웃]은 2번을 부르고 로그인 화면으로 간다 (D-291)', (tester) async {
    final backend = FakeBackend({'POST /api/auth/logout': (_) => json(null, 204)});
    await pumpApp(tester, backend, '/settings');
    await tester.tap(find.widgetWithText(OutlinedButton, '로그아웃'));
    await settle(tester);
    expect(backend.count('POST /api/auth/logout'), 1);
    expect(find.widgetWithText(OutlinedButton, '로그아웃'), findsNothing);
  });

  testWidgets('관리자 계정 설정은 "관리자"를 보이고, 옛 마이페이지 주소는 설정으로 간다 (D-234, D-291)', (tester) async {
    await pumpApp(tester, FakeBackend({}), '/mypage');
    expect(find.text('parking_admin'), findsOneWidget);
    expect(find.text('관리자'), findsOneWidget);
    expect(find.text('사건 관계자'), findsNothing);
    // 메뉴의 [설정]이 지금 화면으로 굵게 보인다 (800 굵기, D-305)
    expect(
      tester.widget<TextButton>(find.widgetWithText(TextButton, '설정')).style?.textStyle?.resolve({})?.fontWeight,
      FontWeight.w800,
    );
  });

  testWidgets('관리자 이용 안내는 캔버스 Info 전체 구성이고, 창 폭이 바뀌어도 넘치지 않는다 (2.13, D-292)', (tester) async {
    await pumpApp(tester, FakeBackend({}), '/info');
    for (final text in ['주차장 관리자 안내', 'CANDIDATE', 'SCREENING', 'CCTV', '5단계로 끝나는 사건 처리', '01', '05', '관리·감독 안내']) {
      expect(find.text(text), findsWidgets, reason: text);
    }
    expect(find.text('관리자 계정 사용법'), findsOneWidget);
    expect(find.text('사건 관계자 계정 사용법'), findsNothing);
    for (final width in [1400.0, 1000.0, 800.0, 420.0]) {
      tester.view.physicalSize = Size(width, 1000);
      await settle(tester);
      expect(tester.takeException(), isNull, reason: '폭 $width');
    }
  });

  testWidgets('이미 로그인한 피해자가 앱을 열면 이용 안내에 사건 관계자 사용법만 보인다 (2.13, D-235)', (tester) async {
    final backend = FakeBackend({}, role: 'victim');
    await pumpApp(tester, backend, '/');
    expect(find.text('사건 관계자 계정 사용법'), findsOneWidget);
    expect(find.text('[채팅]에서 관리자의 사건 초대를 [수락]합니다.'), findsOneWidget);
    expect(find.text('관리자 계정 사용법'), findsNothing);
    // 메뉴의 [Info.]가 지금 화면으로 굵게 보인다 (800 굵기, D-305)
    expect(
      tester.widget<TextButton>(find.widgetWithText(TextButton, 'Info.')).style?.textStyle?.resolve({})?.fontWeight,
      FontWeight.w800,
    );
    // 서버에는 읽기만 했고, 바꾸는 호출은 없다
    expect(backend.calls.where((c) => !c.startsWith('GET ')), isEmpty);
  });

  testWidgets('설정에서 글자 크기 [크게]를 고르면 앱 전체 글자가 커지고 브라우저에 저장된다 (D-236, D-291)', (tester) async {
    final backend = FakeBackend({});
    final browser = FakeBrowser();
    await pumpApp(tester, backend, '/settings', browser: browser);
    double scaleOf() => MediaQuery.textScalerOf(tester.element(find.byType(RadioGroup<TextSize>))).scale(10) / 10;
    RadioGroup<TextSize> picker() => tester.widget(find.byType(RadioGroup<TextSize>));
    // 처음은 [보통], 배율 1.0, 저장값 없음
    expect(picker().groupValue, TextSize.normal);
    expect(scaleOf(), 1.0);
    expect(browser.local, isEmpty);

    await tester.tap(find.text('크게'));
    await settle(tester);
    expect(picker().groupValue, TextSize.large);
    expect(scaleOf(), 1.15);
    expect(browser.local[textSizeStorageKey], 'large');
    // 상단 메뉴(관리자 5개)가 넘치지 않는다 (넘치면 테스트가 예외로 잡는다)
    expect(tester.takeException(), isNull);
    // 서버에는 읽기만 했고, 바꾸는 호출은 없다
    expect(backend.calls.where((c) => !c.startsWith('GET ')), isEmpty);
  });

  testWidgets('설정에서 정해 브라우저에 저장된 글자 크기로 앱이 열리고, 알 수 없는 값이면 보통이다 (2.14, D-236)', (tester) async {
    final backend = FakeBackend({'GET /api/auth/me': (_) => apiError(401, 'UNAUTHENTICATED')});
    // 로그인 화면부터 저장된 크기를 따른다
    await pumpApp(tester, backend, '/', browser: FakeBrowser(local: {textSizeStorageKey: 'small'}));
    expect(find.text('로그인'), findsWidgets);
    expect(MediaQuery.textScalerOf(tester.element(find.byType(Scaffold).first)).scale(10) / 10, 0.9);

    // 알 수 없는 값이면 보통이다 (같은 위젯 트리에서 새 앱으로 바꿔 끼운다)
    await tester.pumpWidget(const SizedBox());
    await pumpApp(tester, backend, '/', browser: FakeBrowser(local: {textSizeStorageKey: '엉뚱한값'}));
    expect(MediaQuery.textScalerOf(tester.element(find.byType(Scaffold).first)).scale(10) / 10, 1.0);
  });

  testWidgets('피해자 계정 목록은 관리자 칸, 연결 메뉴 없음 (2.2, D-204)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([video('ready')]),
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos');
    expect(find.text('사건 1건'), findsOneWidget);
    expect(find.text('관리자'), findsOneWidget); // 표 머리
    expect(find.text('parking_admin'), findsOneWidget);
    expect(find.text('분석 완료'), findsOneWidget); // 피해자는 후보 선택 단계를 보지 않는다
    expect(find.textContaining('영상은 주차장 관리자가 올립니다.'), findsNothing); // 캔버스에 없다 (D-237)
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
        expect(jsonDecode(req.body), {'victim_login_id': 'victim02', 'case_name': 'B2 기둥 긁힘'});
        return json({'id': 3, 'victim_name': 'victim02', 'created_at': '2026-11-01T14:03:00+09:00'}, 201);
      },
      'GET /api/cases': (_) => json({
        'items': [case3()],
      }),
    });
    await pumpApp(tester, backend, '/cases/new');
    expect(backend.screenCallsWithoutBadge, isEmpty); // 열 때는 부르지 않는다

    await tester.enterText(find.byType(TextField).first, '  B2 기둥 긁힘 '); // 앞뒤 공백은 지워 보낸다
    await tester.enterText(find.byType(TextField).last, 'victim02');
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
    await tester.enterText(find.byType(TextField).first, 'B2 기둥 긁힘');
    await tester.enterText(find.byType(TextField).last, 'victim99');
    await tester.tap(find.widgetWithText(FilledButton, '연결'));
    await settle(tester);
    expect(find.text('피해자 계정을 찾을 수 없습니다. 아이디를 다시 확인해 주세요.'), findsOneWidget);
    expect(find.text('사건 관계자 연결'), findsWidgets); // 화면에 머문다
  });

  testWidgets('사건 이름을 비우면 서버를 부르지 않고 칸 아래에 안내 (2.3, D-237)', (tester) async {
    final backend = FakeBackend({});
    await pumpApp(tester, backend, '/cases/new');
    await tester.enterText(find.byType(TextField).last, 'victim02');
    await tester.tap(find.widgetWithText(FilledButton, '연결'));
    await settle(tester);
    expect(find.text('사건 이름을 입력해 주세요.'), findsOneWidget);
    expect(backend.screenCallsWithoutBadge, isEmpty);
  });

  testWidgets('사건 이름으로 검색하면 맞는 줄만 남고, 없으면 검색 결과 없음 안내 (2.2, D-237)', (tester) async {
    final backend = FakeBackend({
      'GET /api/videos': (_) => json([
        video('ready'),
        {...video('queued'), 'video_id': 8, 'case_id': 4},
      ]),
      'GET /api/cases': (_) => json({
        'items': [
          {...case3(), 'case_name': 'B2 기둥 긁힘'},
          {...case3(), 'id': 4, 'case_name': '입구 문콕'},
        ],
      }),
    });
    await pumpApp(tester, backend, '/videos');
    expect(find.text('사건 2건'), findsOneWidget);
    expect(find.text('CH01.mp4'), findsNothing); // 사건 이름만 보이고 파일 이름은 없다 (D-241)

    await tester.enterText(find.widgetWithText(TextField, '사건 이름으로 검색'), '기둥');
    await settle(tester);
    expect(find.text('검색 결과 1건'), findsOneWidget);
    expect(find.text('B2 기둥 긁힘'), findsOneWidget);
    expect(find.text('입구 문콕'), findsNothing);

    await tester.enterText(find.byType(TextField), 'CH09');
    await settle(tester);
    expect(find.text('검색 결과 0건'), findsOneWidget);
    expect(find.text('검색 결과가 없습니다'), findsOneWidget);
    expect(find.text('‘CH09’와 일치하는 사건 이름이 없습니다.\n이름을 다시 확인해 주세요.'), findsOneWidget);
    expect(backend.count('GET /api/videos'), 2); // 검색은 화면에서만 한다. 목록 1번 + 관리자 [알림] 배지 1번 (D-243)
  });

  testWidgets('연필로 사건 이름을 고치면 27번, 휴지통은 확인창 뒤 28번을 부르고 목록을 다시 읽는다 (2.2, D-237)', (tester) async {
    var name = 'B2 기둥 긁힘';
    var deleted = false;
    final backend = FakeBackend({
      'GET /api/videos': (_) => json(deleted ? [] : [video('ready')]),
      'GET /api/cases': (_) => json({
        'items': [
          if (!deleted) {...case3(), 'case_name': name},
        ],
      }),
      'PATCH /api/cases/3': (req) {
        name = jsonDecode(req.body)['case_name'] as String;
        return json({...case3(), 'case_name': name});
      },
      'DELETE /api/cases/3': (_) {
        deleted = true;
        return json(null, 204);
      },
    }, role: 'victim'); // 피해자 계정도 고치고 지울 수 있다
    await pumpApp(tester, backend, '/videos');

    await tester.tap(find.byTooltip('사건 이름 수정'));
    await settle(tester);
    final field = find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField));
    await tester.enterText(field, ' ');
    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await settle(tester);
    expect(find.text('사건 이름을 입력해 주세요.'), findsOneWidget); // 비우면 보내지 않는다
    expect(backend.count('PATCH /api/cases/3'), 0);

    await tester.enterText(field, '지하 1층 긁힘');
    await tester.tap(find.widgetWithText(FilledButton, '저장'));
    await settle(tester);
    expect(backend.count('PATCH /api/cases/3'), 1);
    expect(find.text('지하 1층 긁힘'), findsOneWidget);

    await tester.tap(find.byTooltip('사건 삭제'));
    await settle(tester);
    expect(find.text('사건을 삭제할까요?'), findsOneWidget);
    await tester.tap(find.widgetWithText(OutlinedButton, '취소'));
    await settle(tester);
    expect(backend.count('DELETE /api/cases/3'), 0);

    await tester.tap(find.byTooltip('사건 삭제'));
    await settle(tester);
    await tester.tap(find.widgetWithText(FilledButton, '삭제'));
    await settle(tester);
    expect(backend.count('DELETE /api/cases/3'), 1);
    expect(find.text('사건을 삭제했습니다.'), findsOneWidget);
    expect(find.text('아직 올라온 영상이 없습니다'), findsOneWidget);
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
    expect(backend.screenCallsWithoutBadge, isEmpty);
  });

  testWidgets('관리자 상단 바 메뉴로 사건 목록과 사건 관계자 연결을 오간다 (D-211, D-237)', (tester) async {
    final backend = FakeBackend({'GET /api/videos': (_) => json([])});
    await pumpApp(tester, backend, '/cases/new');
    await tester.tap(find.widgetWithText(TextButton, '사건 목록'));
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
    expect(find.textContaining('사용자 입력 중'), findsOneWidget); // 진행도 4단계
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
    expect(backend.screenCallsWithoutBadge, isEmpty); // 동의는 따로 저장하지 않는다
  });

  testWidgets('녹화 시작 시각은 달력으로 날짜를 고르고 시·분·초를 범위 안에서 치면 형식대로 채워진다 (2.4, D-190, D-242)', (tester) async {
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

    // 시각: 오전/오후는 고르고, 시·분·초는 친다 (D-242)
    await tester.tap(find.text('오전'));
    await settle(tester);
    await tester.tap(find.text('오후').last);
    await settle(tester);
    final dialog = find.byType(AlertDialog);
    Finder box(int i) => find.descendant(of: dialog, matching: find.byType(TextField)).at(i);
    String text(int i) => tester.widget<TextField>(box(i)).controller!.text;
    FilledButton ok() => tester.widget(find.widgetWithText(FilledButton, '확인'));

    // 범위를 넘는 숫자는 들어가지 않는다
    await tester.enterText(box(0), '13');
    await tester.enterText(box(1), '60');
    await settle(tester);
    expect(text(0), '12');
    expect(text(1), '00');
    // 시 0은 [확인]을 막고 안내를 보인다
    await tester.enterText(box(0), '0');
    await settle(tester);
    expect(ok().onPressed, isNull);
    expect(find.text('시는 1~12, 분과 초는 00~59 사이로 입력해 주세요.'), findsOneWidget);

    await tester.enterText(box(0), '9');
    await tester.enterText(box(1), '5');
    await tester.enterText(box(2), '03');
    await settle(tester);
    expect(ok().onPressed, isNotNull);
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
    // 다운로드 기능은 없다 (불변 조건 8)
    expect(find.textContaining('다운로드'), findsNothing);
    expect(find.byIcon(Icons.download), findsNothing);
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
    expect(find.text('초록 선'), findsOneWidget); // ⑧ 확인표 (D-295)

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

  testWidgets('돋보기 [+]로 사진만 확대되고 크기는 그대로이며, 드래그로 옮긴 뒤에도 누른 곳이 원본 좌표로 맞는다 (2.6, D-293)', (tester) async {
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
            'polygon': [[400, 300], [1200, 300], [400, 800]], // 삼각형
          },
        ],
      }),
    }, role: 'victim');
    await pumpApp(tester, backend, '/videos/7/input');

    Rect still() =>
        tester.getRect(find.descendant(of: find.byType(StillCanvas), matching: find.byType(GestureDetector)).first);
    final before = still();
    final scale = before.width / 1920;
    expect(find.text('1배'), findsOneWidget);
    expect(tester.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.zoom_out)).onPressed, isNull);

    // [+] 두 번: 1 → 1.5 → 2배. 화면 가운데를 기준으로 확대한다
    for (var i = 0; i < 2; i++) {
      await tester.tap(find.byTooltip('사진 확대'));
      await tester.pump();
    }
    expect(find.text('2배'), findsOneWidget);
    expect(still(), before); // 사진 칸 크기는 그대로다
    var pan = Offset(before.width / 2, before.height / 2);
    Offset at(double x, double y) => before.topLeft + Offset(x * scale * 2, y * scale * 2) - pan;
    final next = find.widgetWithText(FilledButton, '다음');

    await tester.tapAt(at(500, 400)); // 차 안쪽
    await tester.pump();
    expect(tester.widget<FilledButton>(next).onPressed, isNotNull);
    await tester.tapAt(at(1100, 700)); // 차 밖
    await tester.pump();
    expect(tester.widget<FilledButton>(next).onPressed, isNull);

    // 확대한 상태에서 드래그하면 사진이 손가락을 따라 옮겨진다 (오른쪽 아래로 100·50px 끌면 보이는 곳이 왼쪽 위로)
    await tester.dragFrom(before.center, const Offset(100, 50));
    await tester.pump();
    pan -= const Offset(100, 50);
    await tester.tapAt(at(500, 400)); // 옮긴 뒤에도 같은 원본 위치를 누르면 차가 골라진다
    await tester.pump();
    expect(tester.widget<FilledButton>(next).onPressed, isNotNull);

    // [−]로 1배까지 줄이면 다시 [−]가 막힌다
    for (var i = 0; i < 2; i++) {
      await tester.tap(find.byTooltip('사진 축소'));
      await tester.pump();
    }
    expect(find.text('1배'), findsOneWidget);
    expect(still(), before);
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
