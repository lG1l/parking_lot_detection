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

/// 피해자가 연결을 수락했다. 관리자에게는 상대가 한 일, 피해자에게는 내가 한 일이다 (D-243, D-294).
class NoticeAccepted extends NoticeMessage {
  const NoticeAccepted(this.videoCase);

  final VideoCase videoCase;
}

/// 영상 상태 알림. 카드에 [title]과 [emoji]를 그리고, [chip]은 왼쪽 목록 요약에 쓴다.
/// [problem]이면 제목을 실패 색으로 그린다 (D-243).
class NoticeStatus extends NoticeMessage {
  const NoticeStatus(this.video, this.chip, this.title, this.emoji, {this.problem = false});

  final VideoSummary video;
  final String chip;
  final String title;
  final String emoji;
  final bool problem;
}

/// 연결 요청·수락 카드 문구 (상황별 문구를 이 파일에 모은다).
const inviteEmoji = '🤝';
const acceptedEmoji = '✅';
String inviteTitle({required bool admin}) => admin ? '연결을 요청했어요' : '연결 요청이 왔어요!';
String acceptedTitle({required bool admin}) => admin ? '연결이 수락되었어요!' : '연결을 수락했어요!';

/// 왼쪽 목록 요약에 쓰는 짧은 상태 이름 ("연결 요청", "분석 실패" 등, D-294).
String noticeLabel(NoticeMessage m) => switch (m) {
  NoticeInvite() => '연결 요청',
  NoticeAccepted() => '연결 수락',
  NoticeStatus(:final chip) => chip,
};

/// 내 쪽(오른쪽)에 둘 알림인지. 연결 요청은 관리자가, 연결 수락은 피해자가 한 일이다.
/// 영상 상태 알림은 내게 오는 소식이라 상대 쪽(왼쪽)이다 (D-294).
bool noticeIsMine(NoticeMessage m, {required bool admin}) => switch (m) {
  NoticeInvite() => admin,
  NoticeAccepted() => !admin,
  NoticeStatus() => false,
};

/// 영상 상태 중 계정이 알아야 하는 것만 알림으로 만든다. 나머지는 null.
NoticeStatus? statusNoticeOf(VideoSummary v, {required bool admin}) {
  if (v.maskedDeleted) return null; // 보관 기간이 끝난 영상은 뺀다
  if (admin) {
    return switch (v.status) {
      VideoStatus.stage2Running => NoticeStatus(v, '분석 시작', '영상 분석을 시작했어요!', '🔍'),
      VideoStatus.ready || VideoStatus.batchRunning => NoticeStatus(v, '후보 선정', '후보를 고를 수 있어요!', '🎯'),
      VideoStatus.failed => NoticeStatus(v, '분석 실패', '영상 분석에 실패했어요', '⚠️', problem: true),
      VideoStatus.uploadFailed => NoticeStatus(v, '업로드 실패', '업로드를 확인하지 못했어요', '📤', problem: true),
      _ => null,
    };
  }
  return switch (v.status) {
    VideoStatus.stage1Done => NoticeStatus(v, '입력 필요', '내 차량을 입력해 주세요!', '✏️'),
    VideoStatus.ready || VideoStatus.batchRunning => NoticeStatus(v, '분석 완료', '영상 분석이 끝났어요!', '📊'),
    VideoStatus.finished || VideoStatus.exhausted => NoticeStatus(v, '최종 완료', '사건 시각을 확인했어요!', '🕒'),
    VideoStatus.failed => NoticeStatus(v, '분석 실패', '영상 분석에 실패했어요', '⚠️', problem: true),
    _ => null,
  };
}

/// 사건의 알림. 초대와 (수락했으면) 수락이 먼저, 영상 상태 알림이 뒤따른다.
/// 피해자에게는 수락 전 사건의 영상 알림을 붙이지 않는다(D-233, D-238). 관리자는 수락 전에도 붙인다.
List<NoticeMessage> messagesOf(VideoCase c, List<VideoSummary> videos, {required bool admin}) => [
  NoticeInvite(c),
  if (!c.pending) NoticeAccepted(c),
  if (admin || !c.pending)
    for (final v in videos)
      if (v.caseId == c.id) ?statusNoticeOf(v, admin: admin),
];

/// 관리자 메뉴 [채팅] 배지: 보관 기간이 끝나지 않은 영상 중 할 일(후보 선택 가능·분석 실패·업로드 확인 안 됨) 수 (D-243).
int adminTodoCount(List<VideoSummary> videos) => videos.where((v) {
  if (v.maskedDeleted) return false;
  return v.status == VideoStatus.ready ||
      v.status == VideoStatus.batchRunning ||
      v.status == VideoStatus.failed ||
      v.status == VideoStatus.uploadFailed;
}).length;
