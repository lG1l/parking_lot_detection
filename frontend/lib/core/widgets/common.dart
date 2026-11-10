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
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: title == null ? null : Text(title),
      content: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 392), child: Text(message)),
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

/// 상단 바 가운데 메뉴 (D-190, D-211). [link]는 관리자 계정에만, [notifications]는 피해자 계정에만 있다 (D-233).
enum NavItem { info, videos, link, notifications, myPage }

/// 화면 공통 틀. PC 브라우저 기준이라 가운데 최대 폭을 둔다.
/// 상단 바는 왼쪽 로고 · 가운데 메뉴 · 오른쪽 로그아웃이고, 화면 제목은 본문 맨 위에 둔다 (D-190).
/// 메뉴는 관리자 계정이 [영상 목록]·[사건 관계자 연결], 피해자 계정이 [영상 목록]·[알림]이다 (D-211, D-233).
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

  @override
  Widget build(BuildContext context) {
    final side = isNarrow(context) ? 16.0 : 40.0;
    if (!scrollBody) {
      return Scaffold(
        body: Column(
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
        ),
      );
    }
    return Scaffold(
      body: Column(
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
      ),
    );
  }

  Widget _heading() {
    final eyebrow = this.eyebrow;
    final title = this.title;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (eyebrow != null) ...[
                Wrap(
                  spacing: 12,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      eyebrow,
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: subColor),
                    ),
                    for (final note in eyebrowNotes) ...[
                      const Text('|', style: TextStyle(fontSize: 13, color: noteColor)),
                      Text(note, style: const TextStyle(fontSize: 13, color: noteColor)),
                    ],
                  ],
                ),
                const SizedBox(height: 6),
              ],
              if (title != null) Text(title, style: pageTitleStyle),
            ],
          ),
        ),
        for (final a in actions) ...[const SizedBox(width: 12), a],
      ],
    );
  }
}

/// 화면 제목 글자 (캔버스 h1 26px).
const pageTitleStyle = TextStyle(fontSize: 26, fontWeight: FontWeight.w600, color: inkColor, height: 1.35);

const _barHeight = 72.0;

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

  Future<void> _logout(BuildContext context, WidgetRef ref) async {
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

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(meProvider).value;
    final admin = me?.isAdmin ?? false;
    // 대기 중인 초대 수. 못 읽으면 배지를 두지 않는다 (D-233)
    final invites = me == null || admin ? 0 : ref.watch(pendingInvitesProvider).value?.length ?? 0;
    Widget menu(NavItem item, String label, String path, {int badge = 0}) {
      final selected = item == current;
      return Semantics(
        selected: selected,
        child: TextButton(
          onPressed: () => _leave(context, () {
            ref.invalidate(pendingInvitesProvider); // 화면을 옮길 때 배지 수를 다시 센다 (D-233)
            context.go(path);
          }),
          style: TextButton.styleFrom(
            foregroundColor: selected ? pointColor : inkColor,
            textStyle: TextStyle(
              fontFamily: 'Pretendard',
              fontSize: selected ? 22 : 17,
              fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
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
        if (me != null) menu(NavItem.info, '이용 안내', '/info'),
        menu(NavItem.videos, '영상 목록', '/videos'),
        if (admin) menu(NavItem.link, '사건 관계자 연결', '/cases/new'),
        if (me != null && !admin) menu(NavItem.notifications, '알림', '/notifications', badge: invites),
        if (me != null) menu(NavItem.myPage, '마이페이지', '/mypage'),
      ],
    );
    // 관리자 계정이면 로그아웃 왼쪽에 "관리자 계정"을 보인다 (캔버스)
    final account = admin && !isNarrow(context)
        ? const Text('관리자 계정', style: TextStyle(fontSize: 14, color: subColor))
        : null;
    final logout = TextButton(
      onPressed: () => _leave(context, () => _logout(context, ref)),
      style: TextButton.styleFrom(
        foregroundColor: inkColor,
        textStyle: const TextStyle(
          fontFamily: 'Pretendard',
          fontSize: 16,
          fontWeight: FontWeight.w400,
          decoration: TextDecoration.underline,
        ),
      ),
      child: const Text('로그아웃'),
    );
    if (narrow) {
      // 좁으면 로고 · 메뉴(넘치면 줄여 보임) · 로그아웃을 차례로 둔다
      return Container(
        height: _barHeight,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Row(
          spacing: 8,
          children: [
            const _Logo(size: 36),
            Expanded(
              child: FittedBox(fit: BoxFit.scaleDown, child: nav),
            ),
            logout,
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
              child: _Logo(size: 48), // 그림만. 누르지 않는다 (D-190)
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
                child: Row(mainAxisSize: MainAxisSize.min, spacing: 20, children: [?account, logout]),
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

/// 테두리·옅은 그림자가 있는 흰 카드 (캔버스 `section`).
class PageCard extends StatelessWidget {
  const PageCard({super.key, required this.child, this.padding = const EdgeInsets.all(28), this.border});

  final Widget child;
  final EdgeInsetsGeometry padding;

  /// 기본 1px 연한 회색 선 대신 쓸 테두리 (예: 고정한 후보).
  final BoxBorder? border;

  @override
  Widget build(BuildContext context) => Container(
    padding: padding,
    decoration: BoxDecoration(
      color: offWhiteColor,
      borderRadius: BorderRadius.circular(cardRadius),
      border: border ?? Border.all(color: lineColor),
      boxShadow: cardShadow,
    ),
    // 안의 목록 줄·버튼 물결이 카드 바탕에 가리지 않게 한다
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
        constraints: const BoxConstraints(minHeight: 380),
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
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
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

/// 작게 보이는 보조 문구 (열람기한 등).
class SmallText extends StatelessWidget {
  const SmallText(this.text, {super.key, this.color});

  final String text;
  final Color? color;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: color));
}
