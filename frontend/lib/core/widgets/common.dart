import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../api/api.dart';
import '../api/api_error.dart';
import '../config.dart';
import '../session.dart';

/// 데모에서 백엔드로 보내야 하는 버튼을 눌렀을 때 팝업을 띄울지. 테스트에서는 끈다.
final backendNoticeProvider = Provider<bool>((ref) => !useBackend);

/// 백엔드 연결 필요: 데모에서는 "눌렀다" 팝업을 한 번 띄운다. 닫으면 성공한 것처럼 이어 간다.
/// USE_BACKEND=true면 아무것도 하지 않는다.
Future<void> backendNotice(BuildContext context, WidgetRef ref, String action) async {
  if (!ref.read(backendNoticeProvider)) return;
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text('[$action] 버튼을 눌렀습니다'),
      content: const Text('백엔드 연결 필요 — 지금은 서버에 보내지 않고 예시 데이터로 다음 화면을 보여줍니다.'),
      actions: [FilledButton(onPressed: () => Navigator.pop(context), child: const Text('확인'))],
    ),
  );
}

/// 사용자가 누르지 않았는데 앱이 다른 화면으로 보내는 이동. 브라우저 기록을 새로 쌓지 않고
/// 지금 기록을 바꿔, 뒤로 가기가 사용자가 연 이전 화면으로 가게 한다 (D-185).
void redirectTo(BuildContext context, String path) => Router.neglect(context, () => context.go(path));

/// 로그아웃(2번)하고 로그인 화면으로 간다. 로그아웃은 [설정]의 보안 설정에만 있다 (D-291).
Future<void> logout(BuildContext context, WidgetRef ref) async {
  // 백엔드 연결 필요: 2번 로그아웃
  await backendNotice(context, ref, '로그아웃');
  try {
    await ref.read(apiProvider).logout();
  } on ApiException {
    // 로그아웃은 실패해도 로그인 화면으로 간다
  }
  refreshSession(ref, account: true);
  if (context.mounted) redirectTo(context, '/login');
}

/// 에러 문구를 스낵바로 보인다 (07장 3.1).
void showMessage(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// 모든 화면에 공통인 에러 처리. 문구를 보이고, 화면을 옮겨야 하면 옮긴다.
/// 옮겼으면 true. false면 부른 화면이 code에 맞게 다시 그린다 (07장 3.1).
bool handleCommonError(BuildContext context, Object error) {
  final code = error is ApiException ? error.code : 'INTERNAL_ERROR';
  showMessage(context, errorMessage(code));
  switch (code) {
    case 'UNAUTHENTICATED':
      redirectTo(context, '/login');
      return true;
    case 'VIDEO_NOT_FOUND' || 'CASE_NOT_FOUND' || 'ROLE_NOT_ALLOWED':
      redirectTo(context, '/videos');
      return true;
  }
  return false;
}

String errorCode(Object error) => error is ApiException ? error.code : 'INTERNAL_ERROR';

/// 되돌릴 수 없는 동작 전 확인창. 확인하면 true.
Future<bool> confirm(
  BuildContext context,
  String message, {
  required String okLabel,
  String cancelLabel = '취소',
  String? title,
  Widget? content, // 글자 크기를 섞어 보여야 할 때 message 대신 쓴다
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: title == null ? null : Text(title),
      content: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 392), child: content ?? Text(message)),
      actions: [
        OutlinedButton(onPressed: () => Navigator.pop(context, false), child: Text(cancelLabel)),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(okLabel)),
      ],
    ),
  );
  return ok ?? false;
}

/// 창 폭이 이보다 좁으면 여백·글자를 줄이고 줄을 접는다.
const narrowWidth = 720.0;

bool isNarrow(BuildContext context) => MediaQuery.sizeOf(context).width < narrowWidth;

/// 이 폭보다 좁으면 상단 바 가운데 메뉴가 넘치지 않게 줄여 보인다. 메뉴가 4개(관리자는 5개)라 넓은 배치는 이 폭부터 쓴다 (D-236, D-243, D-291).
const topBarWideWidth = 1000.0;

/// 상단 바 가운데 메뉴 (D-190, D-211). [link]는 관리자 계정에만 있고, [notifications]는 두 계정에 있다 (D-233, D-243).
/// [settings]는 마이페이지와 환경설정을 합친 [설정]이다 (D-291).
enum NavItem { info, videos, link, notifications, settings }

/// 화면 공통 틀. PC 브라우저 기준이라 가운데 최대 폭을 둔다.
/// 상단 바는 왼쪽 로고 · 가운데 메뉴 · 오른쪽 "관리자 계정"(관리자만)이고, 화면 제목은 본문 맨 위에 둔다 (D-190).
/// 로그아웃은 상단 바에 두지 않고 [설정]에 둔다 (D-291).
/// 메뉴는 두 계정 모두 [Info.]·[사건 목록]·[채팅]·[설정]이고, 관리자 계정은 [사건 관계자 연결]이 더 있다 (D-211, D-243, D-291, D-297).
class PageFrame extends StatelessWidget {
  const PageFrame({
    super.key,
    this.title,
    this.eyebrow,
    this.eyebrowNotes = const [],
    required this.child,
    this.actions = const [],
    this.maxWidth = 1200,
    this.current,
    this.canLeave,
    this.scrollBody = true,
    this.titleStrong,
  });

  /// 본문 맨 위 제목. 없으면 두지 않는다.
  final String? title;

  /// 제목 위 작은 글자 (예: "후보 확인"). [eyebrowNotes]는 그 오른쪽에 `|`로 잇는 안내
  /// (예: "피해자 victim02", "2026-10-17 23:59까지 열람 가능").
  final String? eyebrow;
  final List<String> eyebrowNotes;

  final Widget child;

  /// 제목 줄 오른쪽 버튼 (예: [새로고침]).
  final List<Widget> actions;
  final double maxWidth;

  /// 상단 바 메뉴에서 굵게 보일 항목. 없으면 둘 다 보통 굵기.
  final NavItem? current;

  /// 상단 바로 화면을 떠나기 전에 묻는다. false면 머문다 (입력 화면의 저장 안 한 입력).
  final Future<bool> Function()? canLeave;

  /// false면 본문 전체를 스크롤하지 않고 창 높이에 맞춘다. [child]가 남은 높이를 채우고 스크롤할 곳을 스스로 정한다
  /// (후보 확인 화면: 위쪽은 고정, 영상 목록만 스크롤).
  final bool scrollBody;

  /// [title] 안에서 굵게 보일 부분 (예: "사건 12건"의 "12"). 없으면 제목 전체를 굵게 둔다 (D-305).
  final String? titleStrong;

  @override
  Widget build(BuildContext context) {
    final side = isNarrow(context) ? 16.0 : 40.0;
    final Widget body;
    if (!scrollBody) {
      body = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _TopBar(current: current, canLeave: canLeave),
          Expanded(
            child: Padding(
              padding: EdgeInsets.fromLTRB(side, _bodyTop, side, 24),
              child: Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: maxWidth),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (title != null || eyebrow != null) ...[_heading(), const SizedBox(height: 16)],
                      Expanded(child: child),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      );
    } else {
      body = Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _TopBar(current: current, canLeave: canLeave),
          Expanded(
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(side, _bodyTop, side, 40),
              child: Center(
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: maxWidth),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      if (title != null || eyebrow != null) ...[_heading(), const SizedBox(height: 16)],
                      child,
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      );
    }
    // 흰 바탕 + 파란 빛 번짐 두 개가 맨 뒤에 깔린다 (D-305)
    return Scaffold(
      body: Stack(children: [const Positioned.fill(child: _PageGlow()), body]),
    );
  }

  Widget _heading() =>
      PageHeading(title: title, kicker: eyebrow, notes: eyebrowNotes, strong: titleStrong, actions: actions);
}

/// 바탕의 파란 빛 번짐 두 개: 오른쪽 위 · 왼쪽 아래 (캔버스 새 컨셉, D-305).
class _PageGlow extends StatelessWidget {
  const _PageGlow();

  @override
  Widget build(BuildContext context) {
    Widget glow(double size, Color color) => Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(colors: [color, color.withValues(alpha: 0)], stops: const [0, 0.7]),
      ),
    );
    return IgnorePointer(
      child: ExcludeSemantics(
        child: ClipRect(
          child: Stack(
            children: [
              Positioned(right: -260, top: -260, child: glow(720, glowColorTop)),
              Positioned(left: -260, bottom: -260, child: glow(640, glowColorBottom)),
            ],
          ),
        ),
      ),
    );
  }
}

/// 본문 머리: 작은 소제목(있을 때만) + 큰 제목 (캔버스 새 컨셉, D-305). 글자는 07장 그대로 호출하는 쪽이 넘긴다.
/// [strong]이 제목 안에 있으면 그 부분만 굵게 하고 나머지는 얇게 쓴다. 없으면 제목 전체를 굵게 둔다.
class PageHeading extends StatelessWidget {
  const PageHeading({super.key, this.title, this.kicker, this.notes = const [], this.strong, this.actions = const []});

  final String? title;
  final String? kicker;

  /// 소제목 오른쪽에 `|`로 잇는 안내.
  final List<String> notes;
  final String? strong;

  /// 제목 줄 오른쪽 버튼.
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final title = this.title;
    final kicker = this.kicker;
    final size = isNarrow(context) ? 34.0 : 56.0;
    TextStyle style(FontWeight w) =>
        TextStyle(fontSize: size, fontWeight: w, color: inkColor, height: 1.15, letterSpacing: 0);
    Widget titleText(String title) {
      final strong = this.strong;
      final at = strong == null ? -1 : title.indexOf(strong);
      if (strong == null || at < 0) return Text(title, style: style(FontWeight.w600));
      return Text.rich(
        TextSpan(
          style: style(FontWeight.w300),
          children: [
            TextSpan(text: title.substring(0, at)),
            TextSpan(text: strong, style: style(FontWeight.w800)),
            TextSpan(text: title.substring(at + strong.length)),
          ],
        ),
      );
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (kicker != null) ...[
                Wrap(
                  spacing: 12,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(kicker, style: kickerStyle),
                    for (final note in notes) ...[
                      const Text('|', style: TextStyle(fontSize: 13, color: noteColor)),
                      Text(note, style: const TextStyle(fontSize: 13, color: noteColor)),
                    ],
                  ],
                ),
                const SizedBox(height: 10),
              ],
              if (title != null) titleText(title),
            ],
          ),
        ),
        for (final a in actions) ...[const SizedBox(width: 12), a],
      ],
    );
  }
}

/// 작은 소제목 글자 (캔버스 `.k`: 13px 600, 자간 0.08em).
const kickerStyle = TextStyle(fontSize: 13, fontWeight: FontWeight.w600, letterSpacing: 1.04, color: subColor);

/// 화면 안 작은 제목 글자 (26px). 본문 머리의 큰 제목은 [PageHeading].
const pageTitleStyle = TextStyle(fontSize: 26, fontWeight: FontWeight.w600, color: inkColor, height: 1.35);

const _barHeight = 96.0; // 넓은 화면. 좁은 화면은 _narrowBarHeight
const _narrowBarHeight = 72.0;

/// 상단 바와 본문 첫 줄(제목 위 작은 글자, 입력 단계 표시줄 등) 사이 간격. 모든 화면이 같다 (D-190).
const _bodyTop = 8.0;
const _barPadding = EdgeInsets.symmetric(horizontal: 40);

class _TopBar extends ConsumerWidget {
  const _TopBar({this.current, this.canLeave});

  final NavItem? current;
  final Future<bool> Function()? canLeave;

  Future<void> _leave(BuildContext context, VoidCallback go) async {
    final ask = canLeave;
    if (ask != null && !await ask()) return;
    if (context.mounted) go();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(meProvider).value;
    final admin = me?.isAdmin ?? false;
    // 피해자는 대기 중인 초대 수, 관리자는 할 일 수. 못 읽으면 배지를 두지 않는다 (D-233, D-243)
    final badgeCount = me == null ? 0 : ref.watch(notificationBadgeProvider).value ?? 0;
    Widget menu(NavItem item, String label, String path, {int badge = 0}) {
      final selected = item == current;
      return Semantics(
        selected: selected,
        child: TextButton(
          onPressed: () => _leave(context, () {
            ref.invalidate(notificationBadgeProvider); // 화면을 옮길 때 배지 수를 다시 센다 (D-233, D-243)
            context.go(path);
          }),
          style: TextButton.styleFrom(
            foregroundColor: selected ? pointColor : subColor,
            // 지금 화면만 굵게 (캔버스 700 → 가까운 800, D-305)
            textStyle: TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 16,
              fontWeight: selected ? FontWeight.w800 : FontWeight.w500,
            ),
          ),
          child: Badge.count(
            count: badge,
            isLabelVisible: badge > 0,
            offset: const Offset(12, -6),
            child: Text(label),
          ),
        ),
      );
    }

    final narrow = isNarrow(context);
    final nav = Row(
      mainAxisSize: MainAxisSize.min,
      spacing: narrow ? 4 : 32,
      children: [
        // 메뉴 이름은 와이어프레임 캔버스를 따른다 (D-237)
        if (me != null) menu(NavItem.info, 'Info.', '/info'),
        menu(NavItem.videos, '사건 목록', '/videos'),
        if (admin) menu(NavItem.link, '사건 관계자 연결', '/cases/new'),
        if (me != null) menu(NavItem.notifications, '채팅', '/notifications', badge: badgeCount),
        if (me != null) menu(NavItem.settings, '설정', '/settings'),
      ],
    );
    // 관리자 계정이면 오른쪽에 "관리자 계정"을 보인다 (캔버스). 로그아웃은 [설정]에 있다 (D-291)
    final account = admin && !isNarrow(context)
        ? const Text('관리자 계정', style: TextStyle(fontSize: 13, color: subColor))
        : null;
    if (MediaQuery.sizeOf(context).width < topBarWideWidth) {
      // 좁으면 로고 · 메뉴(넘치면 줄여 보임)를 차례로 둔다
      return Container(
        height: _narrowBarHeight,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(
          spacing: 8,
          children: [
            const _Logo(size: 36),
            Expanded(
              child: FittedBox(fit: BoxFit.scaleDown, child: nav),
            ),
          ],
        ),
      );
    }
    return Container(
      height: _barHeight,
      padding: _barPadding,
      child: Row(
        children: [
          const Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: _Logo(size: 40), // 그림만. 누르지 않는다 (D-190)
            ),
          ),
          nav,
          Expanded(
            child: Align(
              alignment: Alignment.centerRight,
              // 창이 빠듯하면 넘치지 않게 조금 줄여 보인다
              child: FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerRight,
                child: account ?? const SizedBox.shrink(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Logo extends StatelessWidget {
  const _Logo({required this.size});

  final double size;

  @override
  Widget build(BuildContext context) =>
      Image.asset('assets/images/logo.png', width: size, height: size, semanticLabel: '서비스 로고');
}

/// 구역 틀. 새 컨셉에서는 상자·그림자 없이 위쪽 1px 연한 선으로 구역을 나눈다 (D-305).
/// [border]를 주면 그 테두리의 상자(모서리 16)로 그린다 (예: 고정한 후보).
class PageCard extends StatelessWidget {
  const PageCard({super.key, required this.child, this.padding = const EdgeInsets.symmetric(vertical: 24), this.border});

  final Widget child;
  final EdgeInsetsGeometry padding;

  /// 상자로 둘러야 할 때 쓸 테두리.
  final BoxBorder? border;

  @override
  Widget build(BuildContext context) => Container(
    padding: border == null ? padding : const EdgeInsets.all(20),
    decoration: border == null
        ? const BoxDecoration(border: Border(top: BorderSide(color: lineColor)))
        : BoxDecoration(borderRadius: BorderRadius.circular(cardRadius), border: border),
    // 안의 목록 줄·버튼 물결이 바탕에 가리지 않게 한다
    child: Material(type: MaterialType.transparency, child: child),
  );
}

/// 가운데 큰 아이콘·제목·설명·버튼을 두는 상태 카드 (빈 목록, 완료, 보관 종료 등).
class StateCard extends StatelessWidget {
  const StateCard({
    super.key,
    this.icon,
    this.iconColor = progressColor,
    this.leading,
    this.title,
    this.messages = const [],
    this.actions = const [],
  });

  final IconData? icon;
  final Color iconColor;

  /// 아이콘 대신 둘 위젯 (예: 진행 표시).
  final Widget? leading;
  final String? title;
  final List<String> messages;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final icon = this.icon;
    final leading = this.leading ?? (icon == null ? null : Icon(icon, size: 64, color: iconColor));
    final title = this.title;
    return PageCard(
      padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 40),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 320),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ?leading,
            if (title != null) ...[
              const SizedBox(height: 16),
              Text(
                title,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
              ),
            ],
            for (final m in messages) ...[
              const SizedBox(height: 12),
              Text(
                m,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 16, height: 1.6, color: subColor),
              ),
            ],
            if (actions.isNotEmpty) ...[
              const SizedBox(height: 24),
              Wrap(spacing: 12, runSpacing: 8, alignment: WrapAlignment.center, children: actions),
            ],
          ],
        ),
      ),
    );
  }
}

/// 상태 카드 안 큰 버튼 (높이 48).
final largeButtonStyle = FilledButton.styleFrom(
  minimumSize: const Size(0, 48),
  padding: const EdgeInsets.symmetric(horizontal: 28),
);

/// 분석·묶음 준비 중 진행 표시 (지름 80, 두께 7).
class BigSpinner extends StatelessWidget {
  const BigSpinner({super.key});

  @override
  Widget build(BuildContext context) =>
      const SizedBox(width: 80, height: 80, child: CircularProgressIndicator(strokeWidth: 7));
}

/// 카드 안 소제목 (캔버스 h2 16px).
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Text(text, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600));
}

/// 안내 문구 블록.
class Notice extends StatelessWidget {
  const Notice(this.text, {super.key, this.icon = Icons.info_outline, this.color = subColor});

  final String text;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return PageCard(
      padding: const EdgeInsets.symmetric(vertical: 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 12),
          Expanded(child: Text(text, style: const TextStyle(fontSize: 15, height: 1.5))),
        ],
      ),
    );
  }
}

/// 카드 안 "이름 | 값" 한 줄 (캔버스 `.kv`). 줄 사이는 위쪽 1px 선이고 첫 줄은 선이 없다.
class KeyValueRow extends StatelessWidget {
  const KeyValueRow({super.key, required this.label, required this.value, this.first = false});

  final String label;
  final Widget value;
  final bool first;

  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 52),
    padding: const EdgeInsets.symmetric(vertical: 6),
    decoration: BoxDecoration(
      border: first ? null : const Border(top: BorderSide(color: lineColor)),
    ),
    child: Row(
      children: [
        SizedBox(
          width: 160,
          child: Text(label, style: const TextStyle(fontSize: 15, color: subColor)),
        ),
        Expanded(child: value),
      ],
    ),
  );
}

/// 카드 안 "이름 ··· 고르기" 한 줄 (캔버스 `.opt`). 줄 전체를 눌러도 고른다.
class OptionRow extends StatelessWidget {
  const OptionRow({super.key, required this.label, required this.trailing, required this.onTap, this.first = false});

  final String label;
  final Widget trailing;
  final VoidCallback onTap;
  final bool first;

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    child: Container(
      constraints: const BoxConstraints(minHeight: 52),
      decoration: BoxDecoration(
        border: first ? null : const Border(top: BorderSide(color: lineColor)),
      ),
      child: Row(
        children: [
          Expanded(child: Text(label, style: const TextStyle(fontSize: 15))),
          trailing,
        ],
      ),
    ),
  );
}

/// 연필 아이콘 버튼 (캔버스: 이름 옆 16px 회색 연필). 이름 수정·아이디 변경에 쓴다.
class EditIconButton extends StatelessWidget {
  const EditIconButton({super.key, required this.tooltip, required this.onPressed});

  final String tooltip;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: tooltip,
    onPressed: onPressed,
    iconSize: 16,
    visualDensity: VisualDensity.compact,
    color: doneChipColor,
    icon: const Icon(Icons.edit_outlined),
  );
}

/// 휴지통 아이콘 버튼 (캔버스: 줄 끝 20px 빨간 휴지통).
class DeleteIconButton extends StatelessWidget {
  const DeleteIconButton({super.key, required this.tooltip, required this.onPressed});

  final String tooltip;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: tooltip,
    onPressed: onPressed,
    iconSize: 20,
    color: failChipColor,
    icon: const Icon(Icons.delete_outline),
  );
}

/// 작게 보이는 보조 문구 (열람기한 등).
class SmallText extends StatelessWidget {
  const SmallText(this.text, {super.key, this.color});

  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: color));
}

/// 상태 점 + 글자의 모양 (07장 2.2, D-305). [dot]이 null이면 속이 빈 회색 테두리 점이다.
typedef StatusDotStyle = ({Color? dot, Color text});

/// 상태 글자(07장 2.2)에서 점 모양을 고른다. 모르는 글자는 회색 점이다.
StatusDotStyle statusDotStyle(String label) => switch (label) {
  '사전 입력 필요' || '확인 완료' => (dot: pointColor, text: pointColor),
  '후보 선택 가능' => (dot: focusLineColor, text: pointColor),
  '분석 완료' => (dot: inkColor, text: inkColor), // 피해자 계정의 분석 완료
  '분석 실패' || '업로드 확인 안 됨' => (dot: failChipColor, text: failChipColor),
  '수락 대기 중' || '종료됨' => (dot: null, text: subColor),
  _ => (dot: progressColor, text: pointColor), // 업로드 중·대기 중·분석 중·업로드 필요, 그 밖
};

/// 상태를 점(7px) + 글자로 보인다. 칩 대신 쓴다 (D-305).
class StatusDot extends StatelessWidget {
  const StatusDot(this.label, {super.key, this.strike = false});

  final String label;

  /// 보관 기간이 끝난 줄처럼 글자에 가운데 줄을 긋는다.
  final bool strike;

  @override
  Widget build(BuildContext context) {
    final style = statusDotStyle(label);
    final dot = style.dot;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 7,
          height: 7,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: dot,
            border: dot == null ? Border.all(color: progressColor, width: 1.5) : null,
          ),
        ),
        const SizedBox(width: 8),
        Flexible(
          child: Text(
            label,
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: style.text,
              decoration: strike ? TextDecoration.lineThrough : null,
            ),
          ),
        ),
      ],
    );
  }
}

/// 선으로만 나눈 표 (D-305). 머리 줄 아래 1px 검은 선, 줄마다 [LineRow]가 연한 선을 긋는다.
class LineTable extends StatelessWidget {
  const LineTable({super.key, this.header, required this.rows});

  /// 머리 줄 (칸 이름). 없으면 선 없이 줄만 둔다.
  final Widget? header;
  final List<Widget> rows;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (header != null)
        Container(
          padding: const EdgeInsets.only(bottom: 12),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: inkColor)),
          ),
          child: header,
        ),
      ...rows,
    ],
  );
}

/// [LineTable]의 한 줄: 높이 64, 아래 1px #E2E8F0 선, 마우스를 올리면 옅은 파란 그라데이션.
/// [onTap]이 있으면 줄 전체를 눌러 연다.
class LineRow extends StatefulWidget {
  const LineRow({super.key, required this.child, this.onTap});

  final Widget child;
  final VoidCallback? onTap;

  @override
  State<LineRow> createState() => _LineRowState();
}

class _LineRowState extends State<LineRow> {
  bool _hover = false;

  @override
  Widget build(BuildContext context) => MouseRegion(
    onEnter: (_) => setState(() => _hover = true),
    onExit: (_) => setState(() => _hover = false),
    cursor: widget.onTap == null ? MouseCursor.defer : SystemMouseCursors.click,
    child: InkWell(
      onTap: widget.onTap,
      hoverColor: Colors.transparent,
      child: Container(
        constraints: const BoxConstraints(minHeight: 64),
        padding: const EdgeInsets.symmetric(vertical: 8),
        decoration: BoxDecoration(
          border: const Border(bottom: BorderSide(color: lineColor)),
          gradient: _hover ? const LinearGradient(colors: [Color(0x143D8BFF), Color(0x003D8BFF)]) : null,
        ),
        child: widget.child,
      ),
    ),
  );
}

/// 진행도·입력 단계: 굵기 4 막대 + 번호·이름 (D-305). [current]는 0부터이고, 그 단계까지 막대가 켜진다.
class StepBar extends StatelessWidget {
  const StepBar({super.key, required this.steps, required this.current});

  final List<String> steps;
  final int current;

  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: 8,
    children: [
      for (var i = 0; i < steps.length; i++)
        Expanded(
          child: Semantics(
            selected: i == current,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  height: 4,
                  decoration: BoxDecoration(
                    color: i <= current ? focusLineColor : lineColor,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  '${(i + 1).toString().padLeft(2, '0')} ${steps[i]}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: i == current ? FontWeight.w600 : FontWeight.w400,
                    // 파랑 글자는 4.5:1이 되는 진한 파랑 (D-305 주의점)
                    color: i == current ? pillColor : subColor,
                  ),
                ),
              ],
            ),
          ),
        ),
    ],
  );
}

/// 연결·업로드 화면 오른쪽의 01·02·03 안내 (D-305). 줄마다 위쪽 1px 연한 선으로 나눈다.
class SideSteps extends StatelessWidget {
  const SideSteps({super.key, required this.items});

  final List<({String title, String text})> items;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      for (var i = 0; i < items.length; i++)
        Container(
          padding: const EdgeInsets.symmetric(vertical: 16),
          decoration: const BoxDecoration(
            border: Border(top: BorderSide(color: lineColor)),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 40,
                child: Text(
                  (i + 1).toString().padLeft(2, '0'),
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: pillColor),
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(items[i].title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    Text(items[i].text, style: const TextStyle(fontSize: 14, height: 1.5, color: subColor)),
                  ],
                ),
              ),
            ],
          ),
        ),
    ],
  );
}
