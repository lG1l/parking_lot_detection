import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
import '../../core/models/account.dart';
import '../../core/session.dart';
import '../../core/settings.dart';
import '../../core/widgets/common.dart';

/// 설정 (두 계정). 마이페이지와 환경설정을 합쳤다 (D-291). 소제목 네 개:
/// 내 계정(닉네임, 계정 유형, 비밀번호 변경) · 보안 설정(로그아웃, 계정 삭제) ·
/// 환경 설정(화면 모드, 글자 크기) · 서비스(1:1 문의/공지사항, 이용약관).
///
/// 실제로 동작하는 것은 [로그아웃](2번)과 글자 크기(브라우저 저장, D-236)뿐이다.
/// 화면 모드는 [라이트]로 표시만 하고, 나머지 버튼은 서버를 부르지 않고 "준비 중인 기능입니다" 안내만 띄운다.
class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(meProvider);
    ref.listen(meProvider, (_, next) {
      if (next.hasError) handleCommonError(context, next.error!);
    });
    return PageFrame(
      current: NavItem.settings,
      title: '설정',
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
            child: _SettingsBody(me: m),
          ),
        ),
      ),
    );
  }
}

/// "준비 중인 기능입니다" 안내 창. 서버를 부르지 않는다.
Future<void> showNotReady(BuildContext context, String feature) => showDialog<void>(
  context: context,
  builder: (context) => AlertDialog(
    title: const Text('준비 중인 기능입니다'),
    content: Text('[$feature]은(는) 아직 사용할 수 없습니다.'),
    actions: [FilledButton(onPressed: () => Navigator.pop(context), child: const Text('확인'))],
  ),
);

class _SettingsBody extends ConsumerWidget {
  const _SettingsBody({required this.me});

  final Me me;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    const value = TextStyle(fontSize: 15);
    void notReady(String feature) => showNotReady(context, feature);
    final size = ref.watch(textSizeProvider);
    void selectSize(TextSize? s) {
      if (s != null) ref.read(textSizeProvider.notifier).select(s);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 12,
      children: [
        const _SectionTitle('내 계정'),
        _SectionCard(
          children: [
            KeyValueRow(
              label: '닉네임',
              first: true,
              value: _ValueWithAction(
                value: Text(me.name, style: value),
                action: EditIconButton(tooltip: '닉네임 변경', onPressed: () => notReady('닉네임 변경')),
              ),
            ),
            KeyValueRow(
              label: '계정 유형',
              value: Text(me.isAdmin ? '관리자' : '사건 관계자', style: value),
            ),
            KeyValueRow(
              label: '비밀번호',
              value: _ValueWithAction(
                value: const SmallText('비밀번호는 변경 후 다시 로그인해야 합니다.'),
                action: OutlinedButton(onPressed: () => notReady('비밀번호 변경'), child: const Text('비밀번호 변경')),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        const _SectionTitle('보안 설정'),
        _SectionCard(
          children: [
            KeyValueRow(
              label: '로그아웃',
              first: true,
              value: _ValueWithAction(
                value: const SmallText('이 브라우저에서 로그아웃합니다.'),
                action: OutlinedButton(onPressed: () => logout(context, ref), child: const Text('로그아웃')),
              ),
            ),
            KeyValueRow(
              label: '계정 삭제',
              value: _ValueWithAction(
                value: const SmallText('계정을 삭제하면 되돌릴 수 없습니다.'),
                action: OutlinedButton(
                  onPressed: () => notReady('계정 삭제'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: failChipColor,
                    side: const BorderSide(color: failChipColor, width: 1.5),
                  ),
                  child: const Text('계정 삭제'),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        const _SectionTitle('환경 설정'),
        _SectionCard(
          children: [
            // 화면 모드는 표시만 한다. 늘 [라이트]이고, [다크]를 누르면 안내만 띄운다
            KeyValueRow(
              label: '화면 모드',
              first: true,
              value: RadioGroup<String>(
                groupValue: 'light',
                onChanged: (v) {
                  if (v == 'dark') notReady('다크 모드');
                },
                child: Wrap(
                  spacing: 24,
                  children: [
                    _InlineOption(label: '라이트', radio: const Radio<String>(value: 'light'), onTap: () {}),
                    _InlineOption(
                      label: '다크',
                      radio: const Radio<String>(value: 'dark'),
                      onTap: () => notReady('다크 모드'),
                    ),
                  ],
                ),
              ),
            ),
            // 글자 크기는 [저장] 없이 바로 앱 전체에 적용되고 브라우저에 저장된다 (D-236)
            KeyValueRow(
              label: '글자 크기',
              value: RadioGroup<TextSize>(
                groupValue: size,
                onChanged: selectSize,
                child: Wrap(
                  spacing: 24,
                  children: [
                    for (final s in TextSize.values)
                      _InlineOption(label: s.label, radio: Radio<TextSize>(value: s), onTap: () => selectSize(s)),
                  ],
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        const _SectionTitle('서비스'),
        _SectionCard(
          children: [
            for (final (i, label) in ['1:1 문의', '공지사항', '이용약관'].indexed)
              OptionRow(
                label: label,
                first: i == 0,
                onTap: () => notReady(label),
                trailing: const Icon(Icons.chevron_right, color: subColor),
              ),
          ],
        ),
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(left: 4),
    child: Text(text, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: inkColor)),
  );
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => PageCard(
    padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 8),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
  );
}

/// 값 왼쪽, 버튼 오른쪽.
class _ValueWithAction extends StatelessWidget {
  const _ValueWithAction({required this.value, required this.action});

  final Widget value;
  final Widget action;

  @override
  Widget build(BuildContext context) => Row(
    spacing: 8,
    children: [
      Expanded(child: value),
      action,
    ],
  );
}

/// 가로로 늘어놓는 "◉ 이름" 선택지 하나. 이름을 눌러도 고른다.
class _InlineOption extends StatelessWidget {
  const _InlineOption({required this.label, required this.radio, required this.onTap});

  final String label;
  final Widget radio;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    borderRadius: BorderRadius.circular(6),
    child: Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          radio,
          Text(label, style: const TextStyle(fontSize: 15)),
        ],
      ),
    ),
  );
}
