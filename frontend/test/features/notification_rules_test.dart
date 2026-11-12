import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/account.dart';
import 'package:parking_lot_frontend/core/models/video.dart';
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
    expect(kinds(messagesOf(_case(pending: true), [_video(VideoStatus.ready)], admin: true)), '연결,후보 선택 가능');
    // 피해자, 수락 전 사건: 초대만 (영상 정보를 보이지 않는다, D-233·D-238)
    expect(kinds(messagesOf(_case(pending: true), [_video(VideoStatus.stage1Done)], admin: false)), '연결');
    // 피해자, 수락한 사건: 기존 알림 그대로
    expect(kinds(messagesOf(_case(), [_video(VideoStatus.stage1Done)], admin: false)), '연결,사전 입력 필요');
    // 보관 기간이 끝난 영상은 알림이 없다
    expect(kinds(messagesOf(_case(), [_video(VideoStatus.ready, expired: true)], admin: true)), '연결,수락함');
    // 업로드 확인 안 됨은 실패 칩 색
    final failed = statusNoticeOf(_video(VideoStatus.uploadFailed), admin: true)!;
    expect((failed.chip, failed.problem), ('업로드 확인 안 됨', true));

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
}
