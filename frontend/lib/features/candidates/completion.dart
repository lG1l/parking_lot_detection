import '../../core/models/video.dart';

/// 2.8 완료 화면 문구. exhausted이고 고정한 것이 없을 때 쓴다.
String completionMessage(VideoDetail d) {
  final total = d.candidateTotal ?? 0;
  final unavailable = d.candidateUnavailable ?? 0;
  // 사건 없음으로 표기하지 않는다 (PRD 3.5, D-50)
  if (total == 0) return '후보 구간이 탐지되지 않았습니다';
  if (unavailable == 0) return '모든 후보를 확인했습니다';
  if (unavailable >= total) {
    return '후보 구간 $total건을 찾았지만 영상을 준비하지 못해 볼 수 없습니다. 운영 담당자에게 문의해 주세요.';
  }
  return partialUnavailableMessage(unavailable);
}

/// "일부 열람 불가" 문구. 결과 화면 위에도 보인다 (07장 2.9, D-109).
String partialUnavailableMessage(int unavailable) =>
    '열람 가능한 후보를 모두 확인했습니다. 열람 불가 $unavailable건이 있습니다.';
