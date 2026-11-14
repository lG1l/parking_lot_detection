import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/router.dart';
import 'app/theme.dart';
import 'core/constants.dart';
import 'core/settings.dart';

void main() {
  runApp(const ProviderScope(child: App()));
}

class App extends ConsumerStatefulWidget {
  const App({super.key, this.initialLocation = '/'});

  /// 테스트에서 시작 화면을 고를 때 쓴다. 웹에서는 주소창의 경로가 먼저다.
  final String initialLocation;

  @override
  ConsumerState<App> createState() => _AppState();
}

class _AppState extends ConsumerState<App> {
  late final _router = createRouter(initialLocation: widget.initialLocation);

  @override
  void dispose() {
    _router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final textSize = ref.watch(textSizeProvider);
    return MaterialApp.router(
      title: serviceName,
      debugShowCheckedModeBanner: false,
      theme: appTheme,
      // 달력·시계 선택창 등 기본 글자를 한국어로 (D-190)
      locale: const Locale('ko'),
      supportedLocales: const [Locale('ko')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      routerConfig: _router,
      // 글자 크기 배율 하나를 앱 맨 바깥에서 곱한다 — 로그인 화면 포함 모든 글자가 함께 바뀐다 (D-236)
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(textSize.scale)),
        child: child!,
      ),
    );
  }
}
