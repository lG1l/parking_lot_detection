import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/account.dart';
import 'package:parking_lot_frontend/core/models/message.dart';
import 'package:parking_lot_frontend/core/models/video.dart';
import 'package:parking_lot_frontend/features/notifications/chat_rules.dart';
import 'package:parking_lot_frontend/features/notifications/notification_rules.dart';

ChatMessage _m(int id) => ChatMessage(id: id, mine: false, body: '$id', createdAt: '2026-11-15T10:00:00Z');

void main() {
  test('메뉴 배지는 기존 수에 안 읽은 채팅 수를 더하고, 29번이 실패해도 기존 수는 남는다 (D-303)', () {
    expect(chatBadgeCount(2, 3), 5);
    expect(chatBadgeCount(2, null), 2);
  });

  test('메시지를 합칠 때 같은 id는 한 번만 두고 id 오름차순이다 (05장 33번)', () {
    final out = mergeMessages([_m(1), _m(2)], [_m(3), _m(2)]);
    expect(out.map((m) => m.id), [1, 2, 3]);
  });

  group('알림과 채팅을 시각순으로 섞는다 (D-335)', () {
    final c = VideoCase(id: 1, victimName: 'v', createdAt: '2026-11-15T01:00:00Z', acceptedAt: '2026-11-15T01:05:00Z');
    VideoSummary video(String? changedAt) => VideoSummary(
      videoId: 10,
      caseId: 1,
      originalFilename: 'a.mp4',
      status: VideoStatus.ready,
      viewExpiresAt: null,
      maskedDeleted: false,
      statusChangedAt: changedAt,
    );
    ChatMessage msg(int id, String at) => ChatMessage(id: id, mine: false, body: '$id', createdAt: at);
    String label(TalkItem t) => switch (t) {
      TalkChat(:final message) => 'chat${message.id}',
      TalkNotice(:final notice) => noticeLabel(notice),
    };
    List<String> run(String? changedAt, List<ChatMessage> chat) {
      final v = video(changedAt);
      return talkTimeline([
        (c, messagesOf(c, [v], admin: false)),
      ], chat).map(label).toList();
    }

    test('영상 상태 알림은 상태가 바뀐 시각 자리에 들어간다', () {
      final chat = [msg(1, '2026-11-15T01:10:00Z'), msg(2, '2026-11-16T02:00:00Z')];
      expect(run('2026-11-16T00:30:00Z', chat), ['연결 요청', '연결 수락', 'chat1', '분석 완료', 'chat2']);
    });

    test('시각이 같으면 알림이 먼저다', () {
      expect(run('2026-11-15T01:10:00Z', [msg(1, '2026-11-15T01:10:00Z')]), ['연결 요청', '연결 수락', '분석 완료', 'chat1']);
    });

    test('status_changed_at이 없으면(이전 서버) 수락 카드 바로 뒤에 둔다', () {
      expect(run(null, [msg(1, '2026-11-15T01:10:00Z')]), ['연결 요청', '연결 수락', '분석 완료', 'chat1']);
    });
  });
}
