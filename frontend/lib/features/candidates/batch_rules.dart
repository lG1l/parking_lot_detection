import '../../core/models/analysis.dart';
import '../../core/models/video.dart';

/// [다음 묶음 받기]를 보일지 (07장 2.7, 05장 5.8).
/// 보고 있는 묶음이 그 탭의 마지막이고, 그 탭을 다 넘기지 않았고, 상태가 ready일 때만.
bool canFetchNext(Batch batch, ListSummary tab, String status) =>
    status == VideoStatus.ready && batch.batchNo == tab.latestBatchNo && !tab.done;

/// 이 탭의 마지막 페이지인지: 받을 후보가 더 없고(remaining 0) 마지막 묶음을 보고 있으며 아직 넘기지 않았다.
/// 이때는 [다음 ▶]을 막고 [확인 완료]로 이 탭을 끝낸다(13번) (D-190).
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

/// 묶음의 열람 불가 안내 (D-109). 없으면 null.
String? unavailableMessage(Batch batch) {
  if (batch.unavailable == 0) return null;
  if (batch.candidates.isEmpty) return '이 묶음의 후보는 모두 영상을 준비하지 못했습니다.';
  return '이 묶음에 영상을 준비하지 못해 볼 수 없는 후보가 ${batch.unavailable}건 있습니다.';
}
