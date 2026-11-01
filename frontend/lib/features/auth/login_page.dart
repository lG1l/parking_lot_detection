import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../app/theme.dart';
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
  final _idFocus = FocusNode();
  final _passwordFocus = FocusNode();
  bool _busy = false;
  bool _showPassword = false;
  String? _idError;
  String? _passwordError;

  /// 서버가 로그인을 거절했을 때 버튼 위에 보이는 문구 (D-190).
  String? _loginError;

  @override
  void dispose() {
    _id.dispose();
    _password.dispose();
    _idFocus.dispose();
    _passwordFocus.dispose();
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
      // 빈 칸으로 커서를 옮겨 바로 다시 입력할 수 있게 한다
      (idError != null ? _idFocus : _passwordFocus).requestFocus();
      return;
    }
    setState(() {
      _busy = true;
      _loginError = null;
    });
    // 백엔드 연결 필요: 1번 로그인
    await backendNotice(context, ref, '로그인');
    try {
      await ref.read(apiProvider).login(_id.text, _password.text);
      if (mounted) redirectTo(context, '/videos');
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _loginError = errorMessage(e.code));
      _passwordFocus.requestFocus();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final loginError = _loginError;
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Container(
            width: 400,
            padding: const EdgeInsets.all(40),
            decoration: BoxDecoration(
              color: offWhiteColor,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: inkColor, width: 1.5),
            ),
            child: AutofillGroup(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Image.asset('assets/images/logo.png', height: 88, semanticLabel: '서비스 로고'),
                  const SizedBox(height: 20),
                  _LabeledField(
                    label: '아이디',
                    child: TextField(
                      controller: _id,
                      focusNode: _idFocus,
                      decoration: InputDecoration(errorText: _idError),
                      onChanged: (_) {
                        if (_idError != null) setState(() => _idError = null);
                      },
                      autofillHints: const [AutofillHints.username],
                      textInputAction: TextInputAction.next,
                    ),
                  ),
                  const SizedBox(height: 20),
                  _LabeledField(
                    label: '비밀번호',
                    child: TextField(
                      controller: _password,
                      focusNode: _passwordFocus,
                      decoration: InputDecoration(
                        errorText: _passwordError,
                        suffixIcon: IconButton(
                          icon: Icon(_showPassword ? Icons.visibility_off : Icons.visibility),
                          tooltip: _showPassword ? '비밀번호 숨기기' : '비밀번호 보기',
                          onPressed: () => setState(() => _showPassword = !_showPassword),
                        ),
                      ),
                      obscureText: !_showPassword,
                      onChanged: (_) {
                        if (_passwordError != null) setState(() => _passwordError = null);
                      },
                      autofillHints: const [AutofillHints.password],
                      // Enter의 기본 동작(칸에서 포커스 빼기)을 막아, 안내가 뜬 뒤에도 바로 다시 입력할 수 있게 한다
                      onEditingComplete: () {},
                      onSubmitted: (_) => _login(),
                    ),
                  ),
                  if (loginError != null) ...[
                    const SizedBox(height: 20),
                    Text(loginError, style: const TextStyle(fontSize: 13, color: failColor)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy ? null : _login,
                    child: _busy
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('로그인'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 입력칸 위에 이름을 두는 칸 (캔버스 로그인 화면).
class _LabeledField extends StatelessWidget {
  const _LabeledField({required this.label, required this.child});

  final String label;
  final Widget child;

  @override
  Widget build(BuildContext context) => Semantics(
    label: label,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
        const SizedBox(height: 6),
        child,
      ],
    ),
  );
}
