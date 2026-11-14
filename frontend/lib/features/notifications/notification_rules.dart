import '../../core/models/account.dart';
import '../../core/models/video.dart';

/// 알림 대화 한 칸 (07장 2.11, D-237, D-243). 사건 초대·수락이거나, 영상 상태에서 만든 알림이다.
/// 위젯이 없는 순수 규칙이라 단위 테스트로 확인한다.
sealed class NoticeMessage {
  const NoticeMessage();
}

/// 연결 요청 말풍선. 피해자는 수락 전이면 [수락] 버튼이 붙는다.
class NoticeInvite extends NoticeMessage {
  const NoticeInvite(this.videoCase);

  final VideoCase videoCase;
}

/// 관리자 알림: 피해자가 연결을 수락했다 (D-243).
class NoticeAccepted extends NoticeMessage {
  const NoticeAccepted(this.videoCase);

  final VideoCase videoCase;
}

/// 영상 상태 알림. [problem]이면 칩을 실패 색으로 그린다 (D-243).
class NoticeStatus extends NoticeMessage {
  const NoticeStatus(this.video, this.chip, this.text, {this.problem = false});

  final VideoSummary video;
  final String chip;
  final String text;
  final bool problem;
}

/// 영상 상태 중 계정이 알아야 하는 것만 알림으로 만든다. 나머지는 null.
NoticeStatus? statusNoticeOf(VideoSummary v, {required bool admin}) {
  if (v.maskedDeleted) return null; // 보관 기간이 끝난 영상은 뺀다
  final name = v.originalFilename;
  if (admin) {
    return switch (v.status) {
      VideoStatus.stage2Running => NoticeStatus(v, '분석 시작', '피해자가 입력을 마쳐 $name 분석을 시작했습니다.'),
      VideoStatus.ready || VideoStatus.batchRunning => NoticeStatus(v, '후보 선택 가능', '$name 분석이 끝났습니다. 후보를 확인해 주세요.'),
      VideoStatus.failed => NoticeStatus(
        v,
        '분석 실패',
        '$name 영상을 분석하지 못했습니다. 영상 상태 화면에서 다시 시도하거나 다시 올려 주세요.',
        problem: true,
      ),
      VideoStatus.uploadFailed => NoticeStatus(
        v,
        '업로드 확인 안 됨',
        '$name 업로드가 확인되지 않습니다. 같은 사건에 다시 올려 주세요.',
        problem: true,
      ),
      _ => null,
    };
  }
  return switch (v.status) {
    VideoStatus.stage1Done => NoticeStatus(v, '사전 입력 필요', '$name 차량과 파손 부위를 입력해 주세요.'),
    VideoStatus.ready || VideoStatus.batchRunning => NoticeStatus(v, '분석 완료', '결과는 주차장 관리자 화면에서 관리자와 함께 확인합니다.'),
    VideoStatus.finished || VideoStatus.exhausted => NoticeStatus(v, '확인 완료', '고정한 사건 지점의 시간을 볼 수 있습니다.'),
    VideoStatus.failed => NoticeStatus(v, '분석 실패', '$name 영상을 분석하지 못했습니다. 관리자에게 문의해 주세요.'),
    _ => null,
  };
}

/// 사건의 알림. 초대(와 관리자는 수락함)가 먼저, 영상 상태 알림이 뒤따른다.
/// 피해자에게는 수락 전 사건의 영상 알림을 붙이지 않는다(D-233, D-238). 관리자는 수락 전에도 붙인다.
List<NoticeMessage> messagesOf(VideoCase c, List<VideoSummary> videos, {required bool admin}) => [
  NoticeInvite(c),
  if (admin && !c.pending) NoticeAccepted(c),
  if (admin || !c.pending)
    for (final v in videos)
      if (v.caseId == c.id) ?statusNoticeOf(v, admin: admin),
];

/// 관리자 메뉴 [알림] 배지: 보관 기간이 끝나지 않은 영상 중 할 일(후보 선택 가능·분석 실패·업로드 확인 안 됨) 수 (D-243).
int adminTodoCount(List<VideoSummary> videos) => videos.where((v) {
  if (v.maskedDeleted) return false;
  return v.status == VideoStatus.ready ||
      v.status == VideoStatus.batchRunning ||
      v.status == VideoStatus.failed ||
      v.status == VideoStatus.uploadFailed;
}).length;
