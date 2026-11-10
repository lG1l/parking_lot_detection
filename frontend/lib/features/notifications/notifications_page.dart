import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api.dart';
import '../../core/format.dart';
import '../../core/models/account.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';

/// 2.11 알림 (피해자). 대기 중인 사건 초대를 보이고, [수락]하면 그 사건이 묶인다 (D-233).
/// 22번은 열 때와 [새로고침]에서만 부른다. 주기적으로 부르지 않는다.
class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});

  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends ConsumerState<NotificationsPage> {
  List<VideoCase>? _invites;
  final _accepting = <int>{}; // [수락]을 누른 사건. 다시 누르지 못하게 막는다
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    // 관리자 계정은 알림이 없다. 피해자가 연결 화면을 열 때와 같이 목록으로 보낸다
    ref.read(meProvider.future).then((me) {
      if (me.isAdmin && mounted) redirectTo(context, '/videos');
    }, onError: (Object e) {
      if (mounted) handleCommonError(context, e);
    });
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final cases = await ref.read(apiProvider).cases(); // 22
      refreshSession(ref); // 메뉴 배지 수도 다시 센다
      if (mounted) setState(() => _invites = [for (final c in cases) if (c.pending) c]);
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _accept(VideoCase c) async {
    setState(() => _accepting.add(c.id));
    try {
      // 백엔드 연결 필요: 26번 사건 초대 수락 (D-233 초안)
      await backendNotice(context, ref, '수락');
      await ref.read(apiProvider).acceptCase(c.id); // 26
      if (!mounted) return;
      showMessage(context, '사건을 수락했습니다. 영상 목록에서 볼 수 있습니다.');
      await _load();
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _accepting.remove(c.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final invites = _invites;
    return PageFrame(
      current: NavItem.notifications,
      title: '알림',
      maxWidth: 800,
      actions: [OutlinedButton(onPressed: _loading ? null : _load, child: const Text('새로고침'))],
      child: invites == null
          ? const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          : invites.isEmpty
          ? const StateCard(icon: Icons.notifications_none, title: '새 알림이 없습니다')
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final c in invites) ...[
                  PageCard(
                    padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${c.adminName ?? ''} 관리자님이 사건에 초대했습니다',
                                style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w500),
                              ),
                              const SizedBox(height: 4),
                              SmallText(formatKstDate(c.createdAt)),
                            ],
                          ),
                        ),
                        const SizedBox(width: 16),
                        FilledButton(
                          onPressed: _accepting.contains(c.id) ? null : () => _accept(c),
                          child: const Text('수락'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}
