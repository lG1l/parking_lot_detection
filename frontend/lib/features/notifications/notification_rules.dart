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

/// 피해자가 연결을 수락했다. 관리자에게는 상대가 한 일, 피해자에게는 내가 한 일이다 (D-243, D-297).
class NoticeAccepted extends NoticeMessage {
  const NoticeAccepted(this.videoCase);

  final VideoCase videoCase;
}

/// 영상 상태 알림. 카드에 [title]과 [emoji]를 그리고, [chip]은 왼쪽 목록 요약에 쓴다.
/// [problem]이면 제목을 실패 색으로 그린다 (D-243).
/// [action]은 카드 아래 버튼 문구로, 누르면 그 영상의 상태 화면으로 간다. 진행이 끝난 알림은 null이라 버튼이 없다 (D-304).
class NoticeStatus extends NoticeMessage {
  const NoticeStatus(this.video, this.chip, this.title, this.emoji, {this.problem = false, this.action});

  final VideoSummary video;
  final String chip;
  final String title;
  final String emoji;
  final bool problem;
  final String? action;
}

/// 연결 요청·수락 카드 문구 (상황별 문구를 이 파일에 모은다).
const inviteEmoji = '🤝';
const acceptedEmoji = '✅';
String inviteTitle({required bool admin}) => admin ? '연결을 요청했어요' : '연결 요청이 왔어요!';
String acceptedTitle({required bool admin}) => admin ? '연결이 수락되었어요!' : '연결을 수락했어요!';

/// 왼쪽 목록 요약에 쓰는 짧은 상태 이름 ("연결 요청", "분석 실패" 등, D-297).
String noticeLabel(NoticeMessage m) => switch (m) {
  NoticeInvite() => '연결 요청',
  NoticeAccepted() => '연결 수락',
  NoticeStatus(:final chip) => chip,
};

/// 내 쪽(오른쪽)에 둘 알림인지. 연결 요청은 관리자가, 연결 수락은 피해자가 한 일이다.
/// 영상 상태 알림은 내게 오는 소식이라 상대 쪽(왼쪽)이다 (D-297).
/// 단, 관리자의 "후보 확인이 끝났어요!"는 관리자가 [확인 끝내기]로 한 일이라 오른쪽이다 (D-354).
bool noticeIsMine(NoticeMessage m, {required bool admin}) => switch (m) {
  NoticeInvite() => admin,
  NoticeAccepted() => !admin,
  NoticeStatus(:final video) => admin && (video.status == VideoStatus.finished || video.status == VideoStatus.exhausted),
};

/// 영상 상태 중 계정이 알아야 하는 것만 알림으로 만든다. 나머지는 null.
NoticeStatus? statusNoticeOf(VideoSummary v, {required bool admin}) {
  if (v.maskedDeleted) return null; // 보관 기간이 끝난 영상은 뺀다
  if (admin) {
    return switch (v.status) {
      // 분석 중에는 관리자가 할 일이 없어 버튼이 없다
      VideoStatus.stage2Running => NoticeStatus(v, '분석 시작', '영상 분석을 시작했어요!', '🔍'),
      VideoStatus.ready || VideoStatus.batchRunning => NoticeStatus(v, '후보 선정', '후보를 고를 수 있어요!', '🎯', action: '후보 선택'),
      VideoStatus.failed => NoticeStatus(v, '분석 실패', '영상 분석에 실패했어요', '⚠️', problem: true, action: '상태 확인'),
      VideoStatus.uploadFailed => NoticeStatus(v, '업로드 실패', '업로드를 확인하지 못했어요', '📤', problem: true, action: '상태 확인'),
      // 후보 확인을 다 끝냈다. 이어서 할 일이 없어 버튼이 없다 (D-354)
      VideoStatus.finished || VideoStatus.exhausted => NoticeStatus(v, '최종 완료', '후보 확인이 끝났어요!', '🏁'),
      _ => null,
    };
  }
  return switch (v.status) {
    VideoStatus.stage1Done => NoticeStatus(v, '입력 필요', '내 차량을 입력해 주세요!', '✏️', action: '차량 입력'),
    VideoStatus.ready || VideoStatus.batchRunning => NoticeStatus(v, '분석 완료', '영상 분석이 끝났어요!', '📊', action: '결과 확인'),
    // 관리자가 후보 확인을 끝냈다. 피해자는 결과 화면에서 사건 시각을 본다 (D-354). 분석 실패는 할 일이 없어 버튼이 없다 (D-304)
    VideoStatus.finished || VideoStatus.exhausted => NoticeStatus(v, '최종 완료', '사건 시각을 확인해 주세요!', '🕒', action: '사건 시각 확인'),
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
int adminTodoCount(List<VideoSummary> videos) => videos.where(_isTodo).length;

bool _isTodo(VideoSummary v) {
  if (v.maskedDeleted) return false;
  return v.status == VideoStatus.ready ||
      v.status == VideoStatus.batchRunning ||
      v.status == VideoStatus.failed ||
      v.status == VideoStatus.uploadFailed;
}

/// 메뉴 배지의 알림 수. 관리자는 할 일 영상, 피해자는 수락 전 초대 중 그 사건 상대의 알림을 본 시각
/// (22번 `notices_seen_at`)보다 늦게 생긴 것만 센다. 할 일을 처리하지 않아도 본 알림은 빠진다 (D-338).
int unseenNoticeCount(List<VideoCase> cases, List<VideoSummary> videos, {required bool admin}) {
  bool unseen(VideoCase c, String at) =>
      c.noticesSeenAt == null || DateTime.parse(at).isAfter(DateTime.parse(c.noticesSeenAt!));
  if (!admin) return cases.where((c) => c.pending && unseen(c, c.createdAt)).length;
  final byId = {for (final c in cases) c.id: c};
  return videos.where((v) {
    if (!_isTodo(v)) return false;
    final c = byId[v.caseId];
    // 사건을 모르는 영상(숨긴 사건 등)은 본 시각을 알 수 없어 그대로 센다
    return c == null || unseen(c, v.statusChangedAt ?? c.acceptedAt ?? c.createdAt);
  }).length;
}
