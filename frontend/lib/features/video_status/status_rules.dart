import '../../core/constants.dart';
import '../../core/models/video.dart';

/// 9번 응답으로 고르는 화면 (05장 5.11 "9번 응답으로 화면 고르기").
/// [analysisDone]은 피해자 계정의 "분석이 끝났습니다" 안내다 (D-204).
enum StatusScreen { expired, waiting, input, candidates, results, exhausted, failed, analysisDone }

/// 순서: masked_deleted → status → (stage1_done이면) input_done. 역할에 따라 갈 곳이 다르다 (D-204).
/// - 입력은 피해자 계정만 한다. 관리자는 입력 전 `stage1_done`에서 기다림 안내를 본다.
/// - 후보 확인은 관리자 계정만 한다. 피해자는 그 단계에서 "분석이 끝났습니다"를 본다.
/// - 결과(고정 목록)는 두 계정 모두 연다. 피해자는 시각만 본다 (D-211).
/// exhausted의 candidate_total·고정 여부는 [StatusScreen.exhausted]를 받은 화면이 본다.
StatusScreen selectScreen(VideoDetail d, {required bool admin}) {
  if (d.maskedDeleted) return StatusScreen.expired;
  return switch (d.status) {
    VideoStatus.stage1Done => d.inputDone || admin ? StatusScreen.waiting : StatusScreen.input,
    VideoStatus.ready || VideoStatus.batchRunning => admin ? StatusScreen.candidates : StatusScreen.analysisDone,
    VideoStatus.finished => StatusScreen.results,
    VideoStatus.exhausted => StatusScreen.exhausted,
    // 기한 만료·원본 파기 실패는 보관 기간 종료와 같은 안내 (07장 2.5 실패 안내)
    VideoStatus.failed => d.errorKind == 'expired' ? StatusScreen.expired : StatusScreen.failed,
    _ => StatusScreen.waiting,
  };
}

/// 관리자 계정이 들어갈 때마다 관리·감독 안내창을 거치는 화면 (07장 2.7, D-204).
bool needsSupervision(StatusScreen screen) =>
    const {StatusScreen.candidates, StatusScreen.results, StatusScreen.exhausted}.contains(screen);

/// 진행도 4단계 이름 (07장 2.5, D-204).
const progressSteps = ['업로드 중', '사용자 입력 중', '영상분석 중', '완료'];

/// 지금 단계 번호(0~3). 실패는 단계를 알 수 없어 null이다.
int? progressStep(VideoDetail d) => switch (d.status) {
  VideoStatus.uploading || VideoStatus.uploadFailed || VideoStatus.queued || VideoStatus.stillsRunning => 0,
  VideoStatus.stage1Done => d.inputDone ? 2 : 1,
  VideoStatus.stage2Running => 2,
  VideoStatus.ready || VideoStatus.batchRunning || VideoStatus.finished || VideoStatus.exhausted => 3,
  _ => null,
};

/// 주기 조회를 계속할지 (07장 2.5). 끝 상태·ready·파기면 멈춘다.
bool shouldPoll(VideoDetail d) {
  if (d.maskedDeleted) return false;
  return !const {
    VideoStatus.finished,
    VideoStatus.exhausted,
    VideoStatus.failed,
    VideoStatus.ready,
  }.contains(d.status);
}

const laterNotice = '이 창을 닫고 나중에 다시 접속해도 됩니다. 분석은 계속 진행됩니다.';

/// 대기 화면 문구 (07장 2.5 상태별 안내 문구). 첫 줄을 크게 보인다.
List<String> waitingMessages(VideoDetail d, {required bool admin}) {
  final ahead = d.queueAhead ?? 0;
  return switch (d.status) {
    VideoStatus.uploading => admin
        ? ['관리자가 영상을 업로드 중이므로 아직 열 수 없습니다.']
        : ['관리자가 영상을 올리고 있습니다.', '업로드가 끝나면 차량과 파손 부위를 입력할 수 있습니다.\n이 창을 닫고 나중에 다시 접속해도 됩니다.'],
    VideoStatus.uploadFailed => [
      admin
          ? '업로드가 확인되지 않습니다 — 큰 파일이면 아직 올라오는 중일 수 있습니다. 중단됐다면 같은 사건에 다시 올려 주세요.'
          : '업로드가 확인되지 않습니다 — 큰 파일이면 아직 올라오는 중일 수 있습니다. 중단됐다면 관리자에게 다시 올려 달라고 요청해 주세요.',
    ],
    VideoStatus.queued => [
      '처리를 대기중입니다. 앞에 $ahead건이 있습니다.',
      '서버를 켜는 데 1~2분이 더 걸릴 수 있습니다.',
    ],
    VideoStatus.stillsRunning => ['차량을 고를 장면을 준비하고 있습니다. 수십 초 걸립니다.'],
    VideoStatus.stage1Done when !d.inputDone => [
      '피해자의 입력을 기다리고 있습니다.',
      '피해자 계정에서 차량과 파손 부위를 입력하면 분석이 시작됩니다.',
    ],
    VideoStatus.stage1Done => [
      '입력을 저장했습니다. 분석 차례를 기다리는 중입니다. 앞에 $ahead건이 있습니다.',
      laterNotice,
    ],
    VideoStatus.stage2Running => ['영상을 분석하고 있습니다.\n24시간 영상 기준 약 20분 걸립니다.', laterNotice],
    _ => ['화면을 준비하고 있습니다.'],
  };
}

/// 피해자 계정의 분석 완료 안내 (07장 2.5, D-204).
const analysisDoneMessages = ['분석이 끝났습니다.', '결과는 주차장 관리자 화면에서 관리자와 함께 확인합니다.'];

/// [upload]는 관리자의 [영상 올리기](같은 사건에 다시 올리기)다.
enum FailureAction { retry, upload, none }

/// 실패 안내 (07장 2.5 "실패 안내", D-112). 서버가 준 error_kind·can_retry만 본다.
/// 다시 시도와 다시 올리기는 관리자 계정만 한다 (D-204).
({String message, FailureAction action}) failureNotice(VideoDetail d, {required bool admin}) {
  if (d.errorKind == 'file') {
    return admin
        ? (
            message: '영상 파일에 문제가 있어 분석할 수 없습니다. 영상 파일을 확인한 뒤 같은 사건에 다시 올려 주세요.',
            action: FailureAction.upload,
          )
        : (
            message: '영상 파일에 문제가 있어 분석할 수 없습니다. 관리자에게 영상 파일을 확인한 뒤 다시 올려 달라고 요청해 주세요.',
            action: FailureAction.none,
          );
  }
  if (d.canRetry == true) {
    if (!admin) {
      return (message: '서비스 문제로 분석을 완료하지 못했습니다. 주차장 관리자에게 다시 시도를 요청해 주세요.', action: FailureAction.none);
    }
    final message = d.errorKind == 'temporary'
        ? '일시적인 서비스 문제로 분석을 완료하지 못했습니다. 다시 시도해 주세요. 문제가 계속되면 운영 담당자에게 문의해 주세요.'
        : '서비스 문제로 분석을 완료하지 못했습니다. 다시 시도해 주세요. 문제가 계속되면 운영 담당자에게 문의해 주세요.';
    return (message: message, action: FailureAction.retry);
  }
  if ((d.retryLeft ?? 0) <= 0) {
    return (
      message: '재시도 가능 횟수($maxUserRetries회)를 모두 사용했습니다. 운영 담당자에게 문의해 주세요.',
      action: FailureAction.none,
    );
  }
  return (message: '서비스 문제로 분석을 완료하지 못했습니다. 운영 담당자에게 문의해 주세요.', action: FailureAction.none);
}
