import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/api_error.dart';
import '../config.dart';
import '../constants.dart';

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
      context.go('/login');
      return true;
    case 'VIDEO_NOT_FOUND':
      context.go('/videos');
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
}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: Text(cancelLabel)),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(okLabel)),
      ],
    ),
  );
  return ok ?? false;
}

/// 화면 공통 틀. PC 브라우저 기준이라 가운데 최대 폭을 둔다.
/// 상단 바 왼쪽은 어느 화면이든 같은 로고이고, 화면 제목은 본문 맨 위에 둔다 (D-184).
class PageFrame extends StatelessWidget {
  const PageFrame({
    super.key,
    this.title,
    required this.child,
    this.actions = const [],
    this.maxWidth = 960,
    this.homeLink = true,
  });

  /// 본문 맨 위 제목. 없으면 두지 않는다(영상 목록).
  final String? title;
  final Widget child;
  final List<Widget> actions;
  final double maxWidth;

  /// 로고를 누르면 영상 목록으로 갈지. 관리자 업로드 화면은 false (D-184).
  final bool homeLink;

  @override
  Widget build(BuildContext context) {
    final title = this.title;
    return Scaffold(
      appBar: AppBar(
        title: _AppLogo(homeLink: homeLink),
        actions: actions,
        automaticallyImplyLeading: false,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Center(
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: maxWidth),
            child: title == null
                ? child
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(title, style: Theme.of(context).textTheme.headlineSmall),
                      const SizedBox(height: 16),
                      child,
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

/// 상단 바 로고 + 서비스 이름. 로고 이미지를 받기 전까지 로그인 화면과 같은 주차 아이콘을 쓴다.
class _AppLogo extends StatelessWidget {
  const _AppLogo({required this.homeLink});

  final bool homeLink;

  @override
  Widget build(BuildContext context) {
    final logo = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.local_parking, size: 28, color: Theme.of(context).colorScheme.primary),
        const SizedBox(width: 8),
        const Text(serviceName),
      ],
    );
    if (!homeLink) return logo;
    return Tooltip(
      message: '영상 목록으로',
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => context.go('/videos'),
        child: Padding(padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4), child: logo),
      ),
    );
  }
}

/// [목록으로] (07장 3.7). 서버를 부르지 않는다.
class BackToListButton extends StatelessWidget {
  const BackToListButton({super.key, this.label = '목록으로', this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: onPressed ?? () => context.go('/videos'),
      icon: const Icon(Icons.list),
      label: Text(label),
    );
  }
}

/// 안내 문구 블록.
class Notice extends StatelessWidget {
  const Notice(this.text, {super.key, this.icon = Icons.info_outline});

  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon),
            const SizedBox(width: 12),
            Expanded(child: Text(text)),
          ],
        ),
      ),
    );
  }
}

/// 작게 보이는 보조 문구 (열람기한 등).
class SmallText extends StatelessWidget {
  const SmallText(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: Theme.of(context).textTheme.bodySmall);
}
