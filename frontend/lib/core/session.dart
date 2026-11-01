import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api/api.dart';
import 'models/account.dart';

/// 로그인한 계정 (3번). 화면은 `role`로 메뉴와 갈 화면을 나눈다 (D-204).
/// 로그인·로그아웃 때 [refreshSession]으로 다시 읽는다.
final meProvider = FutureProvider<Me>((ref) => ref.read(apiProvider).me());

/// 영상 → 그 영상의 사건 (22번 + 8번의 `case_id`). 화면 머리의 "피해자 ○○"·"관리자 ○○"와
/// 관리자의 [영상 올리기]에 쓴다. 9번에는 `case_id`가 없어 목록 두 개를 맞춰 본다.
/// 못 읽으면 빈 표다. 머리의 상대 이름만 빠지고 화면은 그대로 그린다.
final caseOfVideoProvider = FutureProvider<Map<int, VideoCase>>((ref) async {
  final api = ref.read(apiProvider);
  try {
    final (cases, videos) = await (api.cases(), api.videos()).wait;
    final byId = {for (final c in cases) c.id: c};
    return {
      for (final v in videos)
        if (byId[v.caseId] != null) v.videoId: byId[v.caseId]!,
    };
  } catch (_) {
    return {};
  }
});

/// 계정이 바뀌거나 사건·영상이 늘었을 때 다시 읽게 한다.
void refreshSession(WidgetRef ref, {bool account = false}) {
  if (account) ref.invalidate(meProvider);
  ref.invalidate(caseOfVideoProvider);
}
