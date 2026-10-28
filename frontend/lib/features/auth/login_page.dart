import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/constants.dart';
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
  bool _showPassword = false;
  String? _idError;
  String? _passwordError;

  @override
  void dispose() {
    _id.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (_busy) return;
    // 두 칸을 함께 검사해 안내를 한 번에 보인다. 비었으면 서버를 부르지 않는다.
    final idError = _id.text.isEmpty ? '아이디를 입력하세요' : null;
    final passwordError = _password.text.isEmpty ? '비밀번호를 입력하세요' : null;
    if (idError != null || passwordError != null) {
      setState(() {
        _idError = idError;
        _passwordError = passwordError;
      });
      return;
    }
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
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: theme.colorScheme.surfaceContainerLow,
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: AutofillGroup(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Icon(
                        Icons.local_parking,
                        size: 48,
                        color: theme.colorScheme.primary,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        serviceName,
                        textAlign: TextAlign.center,
                        style: theme.textTheme.titleMedium,
                      ),
                      const SizedBox(height: 24),
                      TextField(
                        controller: _id,
                        decoration: InputDecoration(
                          labelText: '아이디',
                          errorText: _idError,
                        ),
                        onChanged: (_) {
                          if (_idError != null) setState(() => _idError = null);
                        },
                        autofillHints: const [AutofillHints.username],
                        textInputAction: TextInputAction.next,
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _password,
                        decoration: InputDecoration(
                          labelText: '비밀번호',
                          errorText: _passwordError,
                          suffixIcon: IconButton(
                            icon: Icon(
                              _showPassword
                                  ? Icons.visibility_off
                                  : Icons.visibility,
                            ),
                            tooltip: _showPassword ? '비밀번호 숨기기' : '비밀번호 보기',
                            onPressed: () =>
                                setState(() => _showPassword = !_showPassword),
                          ),
                        ),
                        obscureText: !_showPassword,
                        onChanged: (_) {
                          if (_passwordError != null) {
                            setState(() => _passwordError = null);
                          }
                        },
                        autofillHints: const [AutofillHints.password],
                        onSubmitted: (_) => _login(),
                      ),
                      const SizedBox(height: 24),
                      FilledButton(
                        onPressed: _busy ? null : _login,
                        child: _busy
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Text('로그인'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
