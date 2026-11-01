import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';

/// 피해자 아이디가 없거나 피해자 계정이 아닐 때 (07장 2.3, 05장 21번).
const inviteeInvalidMessage = '피해자 계정을 찾을 수 없습니다. 아이디를 다시 확인해 주세요.';

/// 관리자 계정이 아니면 목록으로 보낸다. 서버도 403 `ROLE_NOT_ALLOWED`로 막는다 (D-204).
void requireAdmin(BuildContext context, WidgetRef ref) {
  ref.read(meProvider.future).then((me) {
    if (!me.isAdmin && context.mounted) redirectTo(context, '/videos');
  }, onError: (Object e) {
    if (context.mounted) handleCommonError(context, e);
  });
}

/// 2.3 사건 관계자 연결 (관리자). 피해자 아이디를 넣고 [연결]하면 24번으로 가린 이름을 확인하는 창을 띄우고(D-206),
/// 창에서 [연결]하면 수락 단계 없이 사건이 생기고(21번) 그 사건의 업로드 화면으로 간다 (D-204).
class CaseLinkPage extends ConsumerStatefulWidget {
  const CaseLinkPage({super.key});

  @override
  ConsumerState<CaseLinkPage> createState() => _CaseLinkPageState();
}

class _CaseLinkPageState extends ConsumerState<CaseLinkPage> {
  final _victim = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    requireAdmin(context, ref);
  }

  @override
  void dispose() {
    _victim.dispose();
    super.dispose();
  }

  Future<void> _link() async {
    final id = _victim.text.trim();
    if (id.isEmpty) {
      setState(() => _error = '피해자 아이디를 입력하세요');
      return;
    }
    setState(() {
      _busy = true; // 같은 피해자를 두 번 누르면 사건이 둘 생기므로 바로 막는다
      _error = null;
    });
    final api = ref.read(apiProvider);
    try {
      // 아이디 오타로 무관한 계정에 정지 장면이 보이지 않게, 가린 이름으로 한 번 더 확인한다 (D-206)
      final found = await api.lookupInvitee(id); // 24
      if (!mounted) return;
      final ok = await confirm(
        context,
        '${found.loginId} (${found.maskedName}) 님을 연결합니다. 연결하면 이 계정이 영상 정지 장면을 보게 됩니다.',
        title: '피해자 계정을 연결할까요?',
        okLabel: '연결',
      );
      if (!ok || !mounted) return;
      // 백엔드 연결 필요: 21번 사건 생성·피해자 연결
      await backendNotice(context, ref, '연결');
      final created = await api.createCase(found.loginId); // 21
      refreshSession(ref);
      if (mounted) redirectTo(context, '/cases/${created.id}/upload');
    } catch (e) {
      if (!mounted) return;
      if (errorCode(e) == 'INVITEE_INVALID') {
        setState(() => _error = inviteeInvalidMessage);
      } else {
        handleCommonError(context, e);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return PageFrame(
      current: NavItem.link,
      title: '사건 관계자 연결',
      child: Align(
        alignment: Alignment.topLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: PageCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  '피해자 계정을 연결하면 수락 단계 없이 바로 사건 하나로 묶입니다.\n연결한 뒤 그 사건에 CCTV 영상을 올립니다.',
                  style: TextStyle(fontSize: 15, height: 1.6),
                ),
                const SizedBox(height: 16),
                const Text('피해자 아이디', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                TextField(
                  controller: _victim,
                  enabled: !_busy,
                  decoration: InputDecoration(errorText: _error),
                  onChanged: (_) {
                    if (_error != null) setState(() => _error = null);
                  },
                  onSubmitted: (_) => _link(),
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    FilledButton(onPressed: _busy ? null : _link, child: const Text('연결')),
                    const Text('연결하면 영상 올리기 화면으로 넘어갑니다.', style: TextStyle(fontSize: 13, color: noteColor)),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
