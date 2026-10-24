import '../../core/constants.dart';
import '../../core/models/video.dart';

/// 9번 응답으로 고르는 화면 (05장 5.11 "9번 응답으로 화면 고르기").
enum StatusScreen { expired, waiting, input, candidates, results, exhausted, failed }

/// 순서: masked_deleted → status → (stage1_done이면) input_done.
/// exhausted의 candidate_total·고정 여부는 [StatusScreen.exhausted]를 받은 화면이 본다.
StatusScreen selectScreen(VideoDetail d) {
  if (d.maskedDeleted) return StatusScreen.expired;
  return switch (d.status) {
    VideoStatus.stage1Done => d.inputDone ? StatusScreen.waiting : StatusScreen.input,
    VideoStatus.ready || VideoStatus.batchRunning => StatusScreen.candidates,
    VideoStatus.finished => StatusScreen.results,
    VideoStatus.exhausted => StatusScreen.exhausted,
    // 기한 만료·원본 파기 실패는 보관 기간 종료와 같은 안내 (07장 2.5 실패 안내)
    VideoStatus.failed => d.errorKind == 'expired' ? StatusScreen.expired : StatusScreen.failed,
    _ => StatusScreen.waiting,
  };
}

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

/// 대기 화면 문구 (07장 2.5 상태별 안내 문구).
List<String> waitingMessages(VideoDetail d) {
  final ahead = d.queueAhead ?? 0;
  return switch (d.status) {
    VideoStatus.uploading => ['관리자가 영상을 업로드 중이므로 아직 열 수 없습니다.'],
    VideoStatus.uploadFailed => [
      '업로드가 확인되지 않습니다 — 큰 파일이면 아직 올라오는 중일 수 있습니다. '
          '한참 지나도 그대로면 관리자에게 확인하고, 중단됐다면 링크를 다시 발급하세요.',
    ],
    VideoStatus.queued => [
      '처리를 대기중입니다. 앞에 $ahead건이 있습니다.',
      '서버를 켜는 데 1~2분이 더 걸릴 수 있습니다.',
    ],
    VideoStatus.stillsRunning => ['차량을 고를 장면을 준비하고 있습니다. 수십 초 걸립니다.'],
    VideoStatus.stage1Done => [
      '입력을 저장했습니다. 분석 차례를 기다리는 중입니다. 앞에 $ahead건이 있습니다.',
      laterNotice,
    ],
    VideoStatus.stage2Running => ['영상을 분석하고 있습니다. 24시간 영상이면 약 20분 걸립니다.', laterNotice],
    _ => ['화면을 준비하고 있습니다.'],
  };
}

enum FailureAction { retry, uploadLink, none }

/// 실패 안내 (07장 2.5 "실패 안내", D-112). 서버가 준 error_kind·can_retry만 본다.
({String message, FailureAction action}) failureNotice(VideoDetail d) {
  if (d.errorKind == 'file') {
    return (
      message: '영상 파일에 문제가 있어 분석할 수 없습니다. 관리자에게 영상 파일을 확인한 뒤 '
          '새 업로드 링크로 다시 올려 달라고 요청하세요.',
      action: FailureAction.uploadLink,
    );
  }
  if (d.canRetry == true) {
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
