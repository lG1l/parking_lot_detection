import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/widgets/common.dart';

/// 2.1 로그인. 회원가입은 없다 (D-44).
class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _id = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _id.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (_busy || _id.text.isEmpty || _password.text.isEmpty) return;
    setState(() => _busy = true);
    // 백엔드 연결 필요: 1번 로그인
    await backendNotice(context, ref, '로그인');
    try {
      await ref.read(apiProvider).login(_id.text, _password.text);
      if (mounted) context.go('/videos');
    } on ApiException catch (e) {
      if (mounted) showMessage(context, errorMessage(e.code));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PageFrame(
      title: '로그인',
      maxWidth: 400,
      child: AutofillGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _id,
              decoration: const InputDecoration(labelText: '아이디'),
              autofillHints: const [AutofillHints.username],
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _password,
              decoration: const InputDecoration(labelText: '비밀번호'),
              obscureText: true,
              autofillHints: const [AutofillHints.password],
              onSubmitted: (_) => _login(),
            ),
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _busy ? null : _login,
              child: const Text('로그인'),
            ),
          ],
        ),
      ),
    );
  }
}
