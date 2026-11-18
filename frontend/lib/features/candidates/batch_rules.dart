import '../../core/constants.dart';
import '../../core/models/analysis.dart';
import '../../core/models/video.dart';

/// [다음 묶음 받기]를 보일지 (07장 2.7, 05장 5.8).
/// 보고 있는 묶음이 그 탭의 마지막이고, 그 탭을 다 넘기지 않았고, 상태가 ready일 때만.
/// 두 탭이 모두 끝났는데([otherDone]) ready면 13번으로 끝내도록 버튼을 남긴다. 전부 열람 불가일 때 이 길로 끝난다 (D-203).
bool canFetchNext(Batch batch, ListSummary tab, String status, {bool otherDone = false}) =>
    status == VideoStatus.ready && batch.batchNo == tab.latestBatchNo && (!tab.done || otherDone);

/// 이 탭의 전체 묶음 수: 받은 묶음 수 + 남은 후보를 10개씩 묶은 수.
/// [다음 ▶]으로 받기 전부터 "묶음 1 / 3"처럼 끝 번호를 보인다.
int totalBatches(ListSummary tab, int currentBatchNo) {
  final received = tab.latestBatchNo ?? currentBatchNo;
  return received + (tab.remaining + batchSize - 1) ~/ batchSize;
}

/// 이 탭의 마지막 페이지인지: 받을 후보가 더 없고(remaining 0) 마지막 묶음을 보고 있으며 아직 넘기지 않았다.
/// 이때는 [다음 ▶]을 막고 [확인 끝내기]로 이 탭을 끝낸다(13번) (D-190).
bool isLastPage(Batch batch, ListSummary tab, String status) =>
    canFetchNext(batch, tab, status) && tab.remaining == 0;

/// 마지막 [다음]의 확인창을 띄울지. 이 탭의 remaining이 0이고 다른 탭도 다 넘겼을 때만 (D-99).
bool needsLastBatchConfirm(Map<String, ListSummary> lists, String tab) =>
    lists[tab]!.remaining == 0 && lists[CandidateList.other(tab)]!.done;

/// 탭을 누를 수 있는지. 파싱 실패 목록이 비었으면 막는다 (07장 2.7 "비었을 때").
bool tabEnabled(Map<String, ListSummary> lists, String tab) =>
    tab == CandidateList.main || lists[tab]?.latestBatchNo != null;

/// 탭 이름: "후보 20", "점수 미산출 3", 비었으면 "점수 미산출 (0)".
String tabLabel(Map<String, ListSummary> lists, String tab) {
  final name = tab == CandidateList.main ? '후보' : '점수 미산출';
  if (!tabEnabled(lists, tab)) return '$name (0)';
  return '$name ${lists[tab]!.remaining}';
}

/// 한 탭을 다 넘겼고 다른 탭에 남았을 때의 안내 (07장 2.7). 아니면 null.
String? tabDoneMessage(Map<String, ListSummary> lists, String tab) {
  final mine = lists[tab]!;
  final other = lists[CandidateList.other(tab)]!;
  if (!mine.done || other.done) return null;
  if (mine.unavailable > 0) {
    return '이 목록에서 볼 수 있는 후보를 모두 확인했습니다. 열람 불가 ${mine.unavailable}건이 있습니다.';
  }
  return tab == CandidateList.main
      ? '이 목록의 후보를 모두 확인했습니다. 점수 미산출에 확인할 후보가 남아 있습니다.'
      : '이 목록의 후보를 모두 확인했습니다. 후보에 확인할 후보가 남아 있습니다.';
}

/// 영상 전체(두 목록 합계)의 열람 불가 수를 탭 줄 오른쪽에 누를 수 없는 연한 글자로 보인다 (D-109).
/// 묶음이 아니라 전체 수라서 어느 묶음·탭에서도 같은 글자가 고정된다. 0건이면 null.
String? unavailableLabel(Map<String, ListSummary> lists) {
  final total = lists.values.fold<int>(0, (sum, l) => sum + l.unavailable);
  return total == 0 ? null : '볼 수 없는 후보 $total';
}
