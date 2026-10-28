import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/router.dart';
import 'app/theme.dart';

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
      title: '마스킹 기반 주차장 CCTV 후보선별 서비스',
      debugShowCheckedModeBanner: false,
      theme: appTheme,
      routerConfig: _router,
    );
  }
}
