import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/widgets/common.dart';

/// 앱이 처음 열릴 때 3번으로 로그인 여부를 본다. 200이면 목록, 401이면 로그인 (07장 2.1).
class StartPage extends ConsumerStatefulWidget {
  const StartPage({super.key});

  @override
  ConsumerState<StartPage> createState() => _StartPageState();
}

class _StartPageState extends ConsumerState<StartPage> {
  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    var loggedIn = false;
    try {
      await ref.read(apiProvider).me();
      loggedIn = true;
    } on ApiException {
      loggedIn = false;
    }
    if (mounted) redirectTo(context, loggedIn ? '/videos' : '/login');
  }

  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: CircularProgressIndicator()));
}
