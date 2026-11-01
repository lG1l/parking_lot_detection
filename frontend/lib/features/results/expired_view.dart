import 'package:flutter/material.dart';

import '../../core/widgets/common.dart';

/// 2.10 보관 기간 종료. "분석에 실패했다"로 읽히지 않게 쓴다.
/// 실제 파일 삭제 완료 시각은 S3 수명 주기에 따라 다를 수 있어 "삭제되었다"고 단정하지 않는다 (D-136, D-142).
/// 버튼 없이 안내만 둔다. 목록으로는 상단 메뉴로 간다 (D-190).
class ExpiredView extends StatelessWidget {
  const ExpiredView({super.key});

  @override
  Widget build(BuildContext context) {
    return const StateCard(
      icon: Icons.inventory_2_outlined,
      title: '보관 기간이 끝났습니다',
      messages: ['업로드 완료 후 30일이 지나 보관 기간이 끝났습니다. 만료된 영상은 주기적으로 삭제합니다.'],
    );
  }
}
