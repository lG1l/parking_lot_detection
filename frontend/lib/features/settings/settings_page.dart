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
            constraints: const BoxConstraints(maxWidth: 960),
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
    void notReady(String feature) => showNotReady(context, feature);
    final size = ref.watch(textSizeProvider);
    void selectSize(TextSize? s) {
      if (s != null) ref.read(textSizeProvider.notifier).select(s);
    }

    return Padding(
      padding: const EdgeInsets.only(top: 24), // 큰 제목 "설정"과 첫 소제목 사이를 띄운다
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 53, // 소제목 구역 사이
        children: [
          _Section('내 계정', [
            KeyValueRow(
              label: '닉네임',
              value: _ValueWithAction(
                value: Text(me.name),
                action: EditIconButton(tooltip: '닉네임 변경', onPressed: () => notReady('닉네임 변경')),
              ),
            ),
            KeyValueRow(label: '계정 유형', value: Text(me.isAdmin ? '관리자' : '사건 관계자')),
            KeyValueRow(
              label: '비밀번호',
              value: _ValueWithAction(
                value: const SmallText('비밀번호는 변경 후 다시 로그인해야 합니다.'),
                action: _SmallPill(label: '비밀번호 변경', onPressed: () => notReady('비밀번호 변경')),
              ),
            ),
          ]),
          _Section('보안 설정', [
            KeyValueRow(
              label: '로그아웃',
              value: _ValueWithAction(
                value: const SmallText('이 브라우저에서 로그아웃합니다.'),
                action: _SmallPill(label: '로그아웃', onPressed: () => logout(context, ref)),
              ),
            ),
            KeyValueRow(
              label: '계정 삭제',
              value: _ValueWithAction(
                value: const SmallText('계정을 삭제하면 되돌릴 수 없습니다.'),
                action: _SmallPill(label: '계정 삭제', danger: true, onPressed: () => notReady('계정 삭제')),
              ),
            ),
          ]),
          _Section('환경 설정', [
            // 화면 모드는 표시만 한다. 늘 [라이트]이고, [다크]를 누르면 안내만 띄운다
            _Choice(
              label: '화면 모드',
              child: RadioGroup<String>(
                groupValue: 'light',
                onChanged: (v) {
                  if (v == 'dark') notReady('다크 모드');
                },
                child: Wrap(
                  spacing: 20,
                  runSpacing: 12,
                  children: [
                    _ModeButton(label: '라이트', dark: false, selected: true, onTap: () {}),
                    _ModeButton(label: '다크', dark: true, selected: false, onTap: () => notReady('다크 모드')),
                  ],
                ),
              ),
            ),
            // 글자 크기는 [저장] 없이 바로 앱 전체에 적용되고 브라우저에 저장된다 (D-236)
            _Choice(
              label: '글자 크기',
              child: RadioGroup<TextSize>(
                groupValue: size,
                onChanged: selectSize,
                child: Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (final s in TextSize.values)
                      _SizeOption(label: s.label, value: s, selected: s == size, onTap: () => selectSize(s)),
                  ],
                ),
              ),
            ),
          ]),
          _Section('서비스', [
            for (final label in ['1:1 문의', '공지사항', '이용약관']) OptionRow(label: label, onTap: () => notReady(label)),
          ]),
        ],
      ),
    );
  }
}

/// 소제목 줄(검은 아래선) 아래에 `hair` 줄들을 두는 구역.
class _Section extends StatelessWidget {
  const _Section(this.title, this.children);

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Container(
        padding: const EdgeInsets.only(bottom: 10),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: inkColor)),
        ),
        // 다른 화면의 작은 머리글(13px)보다 크게 둔다
        child: Text(
          title,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: inkColor),
        ),
      ),
      ...children,
    ],
  );
}

/// 작은 소제목 아래에 선택지를 두는 줄 (화면 모드·글자 크기).
class _Choice extends StatelessWidget {
  const _Choice({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 14,
      children: [
        Text(label, style: kickerStyle),
        child,
      ],
    ),
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

/// 줄 끝의 작은 알약 버튼 (높이 36). [danger]면 빨간 테두리·글자.
class _SmallPill extends StatelessWidget {
  const _SmallPill({required this.label, required this.onPressed, this.danger = false});

  final String label;
  final VoidCallback onPressed;
  final bool danger;

  @override
  Widget build(BuildContext context) => OutlinedButton(
    onPressed: onPressed,
    style: OutlinedButton.styleFrom(
      minimumSize: const Size(0, 36),
      padding: const EdgeInsets.symmetric(horizontal: 14),
      textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
      foregroundColor: danger ? dangerColor : inkColor,
      side: BorderSide(color: danger ? dangerColor : inkColor, width: 1.5),
    ),
    child: Text(label),
  );
}

/// 화면 모드 그림 단추: 작은 화면 그림 + "◉ 이름". 고른 쪽은 파란 테두리 (표시만, D-291).
class _ModeButton extends StatelessWidget {
  const _ModeButton({required this.label, required this.dark, required this.selected, required this.onTap});

  final String label;
  final bool dark;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    Widget bar(double widthFactor, Color color) => FractionallySizedBox(
      widthFactor: widthFactor,
      alignment: Alignment.centerLeft,
      child: Container(
        height: 7,
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(4)),
      ),
    );
    final stripe = dark ? subColor : lineColor;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        width: 220,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: selected ? focusLineColor : hairColor, width: 1.5),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              height: 76,
              color: dark ? inkColor : Colors.white,
              padding: const EdgeInsets.all(14),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [bar(0.6, stripe), bar(0.85, stripe), bar(0.4, focusLineColor)],
              ),
            ),
            Container(
              padding: const EdgeInsets.fromLTRB(4, 0, 14, 0),
              decoration: const BoxDecoration(
                border: Border(top: BorderSide(color: lineColor)),
              ),
              child: Row(
                children: [
                  Radio<String>(value: dark ? 'dark' : 'light', activeColor: focusLineColor),
                  Text(label, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 글자 크기 알약 하나. 고른 것은 파란 테두리·글자, 아니면 회색 (#4A5568, 4.5:1 이상).
class _SizeOption extends StatelessWidget {
  const _SizeOption({required this.label, required this.value, required this.selected, required this.onTap});

  final String label;
  final TextSize value;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    borderRadius: BorderRadius.circular(999),
    child: Container(
      constraints: const BoxConstraints(minHeight: 44),
      padding: const EdgeInsets.fromLTRB(6, 0, 18, 0),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: selected ? focusLineColor : hairColor, width: 1.5),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Radio<TextSize>(value: value, activeColor: focusLineColor),
          Text(
            label,
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: selected ? pillColor : subColor),
          ),
        ],
      ),
    ),
  );
}
