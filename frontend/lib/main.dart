import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/router.dart';
import 'app/theme.dart';
import 'core/constants.dart';

void main() {
  runApp(const ProviderScope(child: App()));
}

class App extends StatefulWidget {
  const App({super.key, this.initialLocation = '/'});

  /// 테스트에서 시작 화면을 고를 때 쓴다. 웹에서는 주소창의 경로가 먼저다.
  final String initialLocation;

  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> {
  late final _router = createRouter(initialLocation: widget.initialLocation);

  @override
  void dispose() {
    _router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: serviceName,
      debugShowCheckedModeBanner: false,
      theme: appTheme,
      // 달력·시계 선택창 등 기본 글자를 한국어로 (D-190)
      locale: const Locale('ko'),
      supportedLocales: const [Locale('ko')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      routerConfig: _router,
    );
  }
}
