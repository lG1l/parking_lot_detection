import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session.dart';
import '../../core/widgets/common.dart';

/// 2.12 마이페이지 (두 계정). 닉네임(3번 `name`)과 계정 유형을 보인다 (D-234).
/// [닉네임 수정]·[비밀번호 변경]·[계정 삭제]는 서버를 부르지 않고 안내 창만 띄운다.
class MyPage extends ConsumerWidget {
  const MyPage({super.key});

  Future<void> _notice(BuildContext context, String feature) => showDialog<void>(
    context: context,
    builder: (_) => AlertDialog(
      title: const Text('준비 중인 기능입니다'),
      content: Text('[$feature]은(는) 아직 사용할 수 없습니다.'),
      actions: [TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('확인'))],
    ),
  );

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(meProvider);
    ref.listen(meProvider, (_, next) {
      if (next.hasError) handleCommonError(context, next.error!);
    });
    return PageFrame(
      current: NavItem.myPage,
      title: '마이페이지',
      maxWidth: 640,
      child: me.when(
        loading: () => const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator())),
        error: (_, _) => const SizedBox.shrink(),
        data: (m) => PageCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const SmallText('닉네임'),
                        const SizedBox(height: 4),
                        Text(m.name, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
                        const SizedBox(height: 4),
                        const SmallText('로그인 아이디와 다릅니다.'),
                      ],
                    ),
                  ),
                  OutlinedButton(onPressed: () => _notice(context, '닉네임 수정'), child: const Text('닉네임 수정')),
                ],
              ),
              const Divider(height: 40),
              const SmallText('계정 유형'),
              const SizedBox(height: 4),
              Text(
                m.isAdmin ? '관리자' : '사건 관계자',
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
              ),
              const Divider(height: 40),
              Row(
                spacing: 12,
                children: [
                  OutlinedButton(onPressed: () => _notice(context, '비밀번호 변경'), child: const Text('비밀번호 변경')),
                  OutlinedButton(onPressed: () => _notice(context, '계정 삭제'), child: const Text('계정 삭제')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
