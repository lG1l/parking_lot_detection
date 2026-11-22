import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/account.dart';
import 'package:parking_lot_frontend/core/models/video.dart';
import 'package:parking_lot_frontend/features/notifications/chat_rules.dart';
import 'package:parking_lot_frontend/features/notifications/notification_rules.dart';

VideoCase _case({bool pending = false}) => VideoCase(
  id: 1,
  victimName: 'victim02',
  adminName: 'admin',
  createdAt: '2026-11-10T01:00:00Z',
  acceptedAt: pending ? null : '2026-11-10T02:00:00Z',
  pending: pending,
);

VideoSummary _video(String status, {bool expired = false}) => VideoSummary(
  videoId: 10,
  caseId: 1,
  originalFilename: 'a.mp4',
  status: status,
  viewExpiresAt: null,
  maskedDeleted: expired,
);

void main() {
  test('알림 메시지와 할 일 수 규칙 (D-233, D-243)', () {
    String kinds(List<NoticeMessage> ms) => ms
        .map(
          (m) => switch (m) {
            NoticeInvite() => '연결',
            NoticeAccepted() => '수락함',
            NoticeStatus(:final chip) => chip,
          },
        )
        .join(',');

    // 관리자, 수락한 사건 + 분석 중
    expect(kinds(messagesOf(_case(), [_video(VideoStatus.stage2Running)], admin: true)), '연결,수락함,분석 시작');
    // 관리자, 수락 전 사건 + ready: 수락 전이어도 영상 알림이 붙고 수락함은 없다
    expect(kinds(messagesOf(_case(pending: true), [_video(VideoStatus.ready)], admin: true)), '연결,후보 선정');
    // 피해자, 수락 전 사건: 초대만 (영상 정보를 보이지 않는다, D-233·D-238)
    expect(kinds(messagesOf(_case(pending: true), [_video(VideoStatus.stage1Done)], admin: false)), '연결');
    // 피해자, 수락한 사건: 요청·수락(내 쪽)·영상 알림 (D-297)
    expect(kinds(messagesOf(_case(), [_video(VideoStatus.stage1Done)], admin: false)), '연결,수락함,입력 필요');
    // 보관 기간이 끝난 영상은 알림이 없다
    expect(kinds(messagesOf(_case(), [_video(VideoStatus.ready, expired: true)], admin: true)), '연결,수락함');
    // 업로드 확인 안 됨은 실패 칩 색
    final failed = statusNoticeOf(_video(VideoStatus.uploadFailed), admin: true)!;
    expect((failed.chip, failed.problem), ('업로드 실패', true));

    // 할 일 수: ready·batch_running·failed·upload_failed만 센다 (분석 중·확인 완료·만료는 제외)
    expect(
      adminTodoCount([
        _video(VideoStatus.ready),
        _video(VideoStatus.batchRunning),
        _video(VideoStatus.failed),
        _video(VideoStatus.uploadFailed),
        _video(VideoStatus.stage2Running),
        _video(VideoStatus.finished),
        _video(VideoStatus.ready, expired: true),
      ]),
      4,
    );
  });

  test('같은 쪽에서 같은 분에 연달아 오면 맨 아래 칸에만 시각을 붙인다', () {
    const a = '2026-11-16T17:42:10+09:00', b = '2026-11-16T17:42:50+09:00', c = '2026-11-16T17:43:00+09:00';
    expect(showTimeStamp(a, true, nextAt: b, nextMine: true), isFalse); // 같은 분·같은 쪽 → 위 칸은 뺀다
    expect(showTimeStamp(b, true), isTrue); // 맨 아래
    expect(showTimeStamp(a, true, nextAt: c, nextMine: true), isTrue); // 분이 다르다
    expect(showTimeStamp(a, true, nextAt: b, nextMine: false), isTrue); // 쪽이 다르다
    expect(showTimeStamp(a, true, nextAt: null, nextMine: true), isTrue); // 아래 칸에 시각이 없다
    expect(showTimeStamp(null, true), isFalse);
  });

  test('할 일이 남은 영상 상태 알림만 버튼 문구가 있고, 진행이 끝난 알림은 없다 (D-304)', () {
    String? action(String status, {required bool admin}) => statusNoticeOf(_video(status), admin: admin)?.action;

    expect(action(VideoStatus.stage1Done, admin: false), '차량 입력');
    expect(action(VideoStatus.ready, admin: false), '결과 확인');
    expect(action(VideoStatus.finished, admin: false), isNull); // 최종 완료는 버튼이 없다
    expect(action(VideoStatus.failed, admin: false), isNull);
    expect(action(VideoStatus.stage2Running, admin: true), isNull); // 분석 시작은 버튼이 없다
    expect(action(VideoStatus.ready, admin: true), '후보 선택');
    expect(action(VideoStatus.uploadFailed, admin: true), '상태 확인');
  });

  test('메뉴 배지는 그 상대의 알림을 본 시각 뒤에 생긴 것만 센다 (D-338)', () {
    VideoCase seenCase({bool pending = false, String? seen}) => VideoCase(
      id: 1,
      victimName: 'victim02',
      createdAt: '2026-11-10T01:00:00Z',
      acceptedAt: pending ? null : '2026-11-10T02:00:00Z',
      pending: pending,
      noticesSeenAt: seen,
    );
    VideoSummary todo(String changedAt) => VideoSummary(
      videoId: 10,
      caseId: 1,
      originalFilename: 'a.mp4',
      status: VideoStatus.ready,
      viewExpiresAt: null,
      maskedDeleted: false,
      statusChangedAt: changedAt,
    );

    // 관리자: 할 일이 남아도 본 뒤면 빠지고, 본 뒤에 바뀐 것만 센다
    final videos = [todo('2026-11-11T00:00:00Z'), todo('2026-11-12T00:00:00Z')];
    expect(unseenNoticeCount([seenCase()], videos, admin: true), 2);
    expect(unseenNoticeCount([seenCase(seen: '2026-11-11T00:00:00Z')], videos, admin: true), 1);
    expect(unseenNoticeCount([seenCase(seen: '2026-11-12T00:00:00Z')], videos, admin: true), 0);
    // 피해자: 본 초대는 수락하지 않아도 빠진다
    expect(unseenNoticeCount([seenCase(pending: true)], const [], admin: false), 1);
    expect(unseenNoticeCount([seenCase(pending: true, seen: '2026-11-10T01:00:00Z')], const [], admin: false), 0);
  });
}
