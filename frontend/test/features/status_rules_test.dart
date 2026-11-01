import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/video.dart';
import 'package:parking_lot_frontend/features/candidates/completion.dart';
import 'package:parking_lot_frontend/features/video_status/status_rules.dart';

VideoDetail detail(
  String status, {
  bool inputDone = false,
  bool maskedDeleted = false,
  int? total,
  int? unavailable,
  String? errorKind,
  bool? canRetry,
  int? retryLeft,
}) => VideoDetail(
  videoId: 1,
  originalFilename: 'a.mp4',
  status: status,
  inputDone: inputDone,
  rawDeleted: maskedDeleted,
  maskedDeleted: maskedDeleted,
  candidateTotal: total,
  candidateUnavailable: unavailable,
  errorKind: errorKind,
  canRetry: canRetry,
  retryLeft: retryLeft,
);

void main() {
  group('9번 응답으로 화면 고르기 (05장 5.11)', () {
    test('masked_deleted를 status보다 먼저 본다', () {
      expect(selectScreen(detail('ready', maskedDeleted: true), admin: true), StatusScreen.expired);
      expect(selectScreen(detail('finished', maskedDeleted: true), admin: false), StatusScreen.expired);
    });

    test('stage1_done은 input_done으로 입력과 대기를 가른다. 입력은 피해자 계정만 한다 (D-204)', () {
      expect(selectScreen(detail('stage1_done'), admin: false), StatusScreen.input);
      expect(selectScreen(detail('stage1_done'), admin: true), StatusScreen.waiting);
      expect(selectScreen(detail('stage1_done', inputDone: true), admin: false), StatusScreen.waiting);
    });

    test('상태별 화면 (관리자 계정)', () {
      expect(selectScreen(detail('queued'), admin: true), StatusScreen.waiting);
      expect(selectScreen(detail('upload_failed'), admin: true), StatusScreen.waiting);
      expect(selectScreen(detail('ready'), admin: true), StatusScreen.candidates);
      expect(selectScreen(detail('batch_running'), admin: true), StatusScreen.candidates);
      expect(selectScreen(detail('finished'), admin: true), StatusScreen.results);
      expect(selectScreen(detail('exhausted'), admin: true), StatusScreen.exhausted);
      expect(selectScreen(detail('failed', errorKind: 'service'), admin: true), StatusScreen.failed);
      expect(selectScreen(detail('failed', errorKind: 'expired'), admin: true), StatusScreen.expired);
    });

    test('피해자 계정은 후보 확인 대신 분석 완료 안내, 결과는 연다 (D-204, D-211)', () {
      expect(selectScreen(detail('ready'), admin: false), StatusScreen.analysisDone);
      expect(selectScreen(detail('batch_running'), admin: false), StatusScreen.analysisDone);
      expect(selectScreen(detail('finished'), admin: false), StatusScreen.results);
    });
  });

  test('진행도 4단계 (D-204)', () {
    expect(progressStep(detail('uploading')), 0);
    expect(progressStep(detail('stills_running')), 0);
    expect(progressStep(detail('stage1_done')), 1);
    expect(progressStep(detail('stage1_done', inputDone: true)), 2);
    expect(progressStep(detail('stage2_running')), 2);
    expect(progressStep(detail('exhausted')), 3);
    expect(progressStep(detail('failed')), isNull);
  });

  test('주기 조회는 끝 상태·ready·파기에서 멈추고 batch_running에서는 계속한다', () {
    expect(shouldPoll(detail('queued')), isTrue);
    expect(shouldPoll(detail('batch_running')), isTrue);
    expect(shouldPoll(detail('ready')), isFalse);
    expect(shouldPoll(detail('failed')), isFalse);
    expect(shouldPoll(detail('queued', maskedDeleted: true)), isFalse);
  });

  test('대기 문구에 앞에 N건을 넣는다', () {
    final d = VideoDetail(
      videoId: 1,
      originalFilename: 'a.mp4',
      status: 'queued',
      queueAhead: 2,
      inputDone: false,
      rawDeleted: false,
      maskedDeleted: false,
    );
    expect(waitingMessages(d, admin: true).first, '처리를 대기중입니다. 앞에 2건이 있습니다.');
  });

  group('실패 안내 (D-112)', () {
    test('재시도 가능하면 버튼', () {
      final n = failureNotice(detail('failed', errorKind: 'temporary', canRetry: true, retryLeft: 2), admin: true);
      expect(n.action, FailureAction.retry);
      expect(n.message, startsWith('일시적인 서비스 문제로'));
    });

    test('횟수 소진이면 문의 안내만', () {
      final n = failureNotice(detail('failed', errorKind: 'service', canRetry: false, retryLeft: 0), admin: true);
      expect(n.action, FailureAction.none);
      expect(n.message, contains('3회'));
    });

    test('파일 문제면 관리자에게만 [영상 올리기]', () {
      final d = detail('failed', errorKind: 'file', canRetry: false, retryLeft: 3);
      expect(failureNotice(d, admin: true).action, FailureAction.upload);
      expect(failureNotice(d, admin: false).action, FailureAction.none);
    });

    test('다시 시도 버튼은 관리자 계정에만 (D-204)', () {
      final d = detail('failed', errorKind: 'temporary', canRetry: true, retryLeft: 2);
      expect(failureNotice(d, admin: false).action, FailureAction.none);
    });
  });

  group('완료 문구 (07장 2.8)', () {
    test('후보 0건은 사건 없음으로 쓰지 않는다', () {
      expect(completionMessage(detail('exhausted', total: 0, unavailable: 0)), '후보 구간이 탐지되지 않았습니다');
    });

    test('열람 불가 수에 따라 고른다', () {
      expect(completionMessage(detail('exhausted', total: 5, unavailable: 0)), '모든 후보를 확인했습니다');
      expect(completionMessage(detail('exhausted', total: 5, unavailable: 2)), contains('열람 불가 2건'));
      expect(completionMessage(detail('exhausted', total: 5, unavailable: 5)), startsWith('후보 구간 5건을 찾았지만'));
    });
  });
}
