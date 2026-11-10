import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session.dart';
import '../../core/widgets/common.dart';

// 사용법 문구의 원본은 07장 2.13이다. 화면 흐름이 바뀌면 함께 고친다 (D-235).
const _adminSteps = [
  '[사건 관계자 연결]에서 피해자 계정 아이디를 입력해 사건에 초대합니다.',
  '위탁계약에 동의하고 CCTV 영상을 올립니다. 피해자가 초대를 수락하기 전에도 올릴 수 있습니다.',
  '[영상 목록]에서 영상을 눌러 진행도를 봅니다. 피해자가 차량과 파손 부위를 입력하면 분석이 시작됩니다.',
  '분석이 끝나면 관리·감독 안내에 동의한 뒤, 피해자와 함께 후보 영상을 확인하고 찾은 장면을 [찾음]으로 고정합니다.',
  '확인을 끝내면 결과 화면에서 고정한 장면의 원본 영상 기준 시간을 봅니다.',
];

const _victimSteps = [
  '[알림]에서 관리자의 사건 초대를 [수락]합니다.',
  '[영상 목록]에서 영상을 눌러 진행도를 봅니다.',
  '영상이 준비되면 내 차량과 파손 부위를 입력합니다.',
  '분석이 끝나면 관리자 화면에서 관리자와 함께 후보 영상을 확인합니다.',
  '확인이 끝나면 [영상 목록]에서 고정한 사건 지점의 시간을 다시 볼 수 있습니다. 경찰에 신고할 때 전달하세요.',
];

/// 2.13 이용 안내 (두 계정). 로그인 뒤 첫 화면이며 계정에 맞는 사용법만 보인다 (D-235).
/// 3번(`meProvider`)만 부르고 새 API는 없다.
class InfoPage extends ConsumerWidget {
  const InfoPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(meProvider);
    ref.listen(meProvider, (_, next) {
      if (next.hasError) handleCommonError(context, next.error!);
    });
    return PageFrame(
      current: NavItem.info,
      title: '이용 안내',
      maxWidth: 800,
      child: me.when(
        loading: () => const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator())),
        error: (_, _) => const SizedBox.shrink(),
        data: (m) {
          final steps = m.isAdmin ? _adminSteps : _victimSteps;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('주차 중 생긴 차량 파손 장면을 CCTV 영상에서 찾도록 돕는 서비스입니다.', style: TextStyle(fontSize: 16)),
              const SizedBox(height: 16),
              PageCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      m.isAdmin ? '관리자 계정 사용법' : '사건 관계자 계정 사용법',
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 16),
                    for (var i = 0; i < steps.length; i++)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            SizedBox(width: 28, child: Text('${i + 1}.', style: const TextStyle(fontWeight: FontWeight.w600))),
                            Expanded(child: Text(steps[i])),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
