import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';

/// 2.12 마이페이지 (두 계정). 아이디와 계정 유형을 보인다 (D-234, 모양은 캔버스 D-237).
/// [아이디 변경]·[비밀번호 변경]·[계정 삭제]는 서버를 부르지 않고 안내 창만 띄운다.
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
      child: me.when(
        loading: () => const Padding(
          padding: EdgeInsets.all(32),
          child: Center(child: CircularProgressIndicator()),
        ),
        error: (_, _) => const SizedBox.shrink(),
        data: (m) => Align(
          alignment: Alignment.topLeft,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 20,
              children: [
                PageCard(
                  padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      KeyValueRow(
                        label: '아이디',
                        first: true,
                        value: Row(
                          spacing: 4,
                          children: [
                            Flexible(child: Text(m.loginId, style: const TextStyle(fontSize: 15))),
                            EditIconButton(tooltip: '아이디 변경', onPressed: () => _notice(context, '아이디 변경')),
                          ],
                        ),
                      ),
                      KeyValueRow(
                        label: '계정 유형',
                        value: Text(m.isAdmin ? '관리자' : '사건 관계자', style: const TextStyle(fontSize: 15)),
                      ),
                    ],
                  ),
                ),
                _ButtonWithNote(
                  button: OutlinedButton(onPressed: () => _notice(context, '비밀번호 변경'), child: const Text('비밀번호 변경')),
                  note: '비밀번호는 변경 후 다시 로그인해야 합니다.',
                ),
                _ButtonWithNote(
                  button: OutlinedButton(
                    onPressed: () => _notice(context, '계정 삭제'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: failChipColor,
                      side: const BorderSide(color: failChipColor, width: 1.5),
                    ),
                    child: const Text('계정 삭제'),
                  ),
                  note: '계정을 삭제하면 되돌릴 수 없습니다.',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ButtonWithNote extends StatelessWidget {
  const _ButtonWithNote({required this.button, required this.note});

  final Widget button;
  final String note;

  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 12,
    runSpacing: 6,
    crossAxisAlignment: WrapCrossAlignment.center,
    children: [button, SmallText(note)],
  );
}
