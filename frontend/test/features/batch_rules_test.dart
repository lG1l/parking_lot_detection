import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/models/analysis.dart';
import 'package:parking_lot_frontend/features/candidates/batch_rules.dart';

ListSummary s(int? latest, int remaining, bool done, {int unavailable = 0}) =>
    ListSummary(latestBatchNo: latest, remaining: remaining, done: done, unavailable: unavailable);

Batch batch(int no, {int unavailable = 0, int count = 1}) => Batch(
  list: 'main',
  batchNo: no,
  unavailable: unavailable,
  candidates: [
    for (var i = 0; i < count; i++)
      CandidateClip(candidateClipId: i, rank: i + 1, vlmScore: 50, startSec: 0, endSec: 30, clipUrl: 'u'),
  ],
  lists: const {},
);

void main() {
  test('[다음 묶음 받기]는 마지막 묶음·안 넘김·ready일 때만 (05장 5.8)', () {
    expect(canFetchNext(batch(2), s(2, 10, false), 'ready'), isTrue);
    expect(canFetchNext(batch(1), s(2, 10, false), 'ready'), isFalse);
    expect(canFetchNext(batch(2), s(2, 0, true), 'ready'), isFalse);
    expect(canFetchNext(batch(2), s(2, 10, false), 'batch_running'), isFalse);
  });

  test('마지막 페이지는 받을 후보가 없고 마지막 묶음을 아직 넘기지 않았을 때 (D-190)', () {
    expect(isLastPage(batch(2), s(2, 0, false), 'ready'), isTrue);
    expect(isLastPage(batch(2), s(2, 10, false), 'ready'), isFalse); // 받을 후보가 남았다 → [다음 ▶]
    expect(isLastPage(batch(1), s(2, 0, false), 'ready'), isFalse); // 앞 묶음
    expect(isLastPage(batch(2), s(2, 0, true), 'ready'), isFalse); // 이미 끝낸 탭
  });

  test('마지막 [다음] 확인창은 다른 탭도 다 넘겼을 때만 (D-99)', () {
    expect(needsLastBatchConfirm({'main': s(3, 0, false), 'parse_failed': s(null, 0, true)}, 'main'), isTrue);
    expect(needsLastBatchConfirm({'main': s(3, 0, false), 'parse_failed': s(1, 2, false)}, 'main'), isFalse);
    expect(needsLastBatchConfirm({'main': s(3, 5, false), 'parse_failed': s(null, 0, true)}, 'main'), isFalse);
  });

  test('비어 있는 점수 미산출 탭은 (0)으로 막는다', () {
    final lists = {'main': s(1, 20, false), 'parse_failed': s(null, 0, true)};
    expect(tabEnabled(lists, 'parse_failed'), isFalse);
    expect(tabLabel(lists, 'parse_failed'), '점수 미산출 (0)');
    expect(tabLabel(lists, 'main'), '후보 20');
  });

  test('한 탭을 다 넘기고 다른 탭이 남았을 때 안내', () {
    expect(
      tabDoneMessage({'main': s(2, 0, true), 'parse_failed': s(1, 3, false)}, 'main'),
      '이 목록의 후보를 모두 확인했습니다. 점수 미산출에 확인할 후보가 남아 있습니다.',
    );
    expect(
      tabDoneMessage({'main': s(2, 0, true, unavailable: 1), 'parse_failed': s(1, 3, false)}, 'main'),
      contains('열람 불가 1건'),
    );
    expect(tabDoneMessage({'main': s(2, 0, true), 'parse_failed': s(null, 0, true)}, 'main'), isNull);
  });

  test('열람 불가 안내 (D-109)', () {
    expect(unavailableMessage(batch(1)), isNull);
    expect(unavailableMessage(batch(1, unavailable: 2)), contains('2건'));
    expect(unavailableMessage(batch(1, unavailable: 3, count: 0)), '이 묶음의 후보는 모두 영상을 준비하지 못했습니다.');
  });
}
