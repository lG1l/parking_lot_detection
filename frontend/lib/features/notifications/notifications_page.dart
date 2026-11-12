import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/format.dart';
import '../../core/models/account.dart';
import '../../core/models/video.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';
import 'notification_rules.dart';

/// 2.11 알림 (두 계정). 왼쪽은 사건, 오른쪽은 고른 사건의 알림 대화다 (캔버스, D-237).
/// 대기 중인 사건 초대는 피해자가 [수락]하면 그 사건이 묶인다 (D-233). 관리자는 [수락]이 없고 할 일을 본다 (D-243).
/// 거절과 메시지 보내기는 없다.
/// 22번·8번은 열 때와 [수락] 뒤에만 부른다. 주기적으로 부르지 않는다.
class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});

  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends ConsumerState<NotificationsPage> {
  List<VideoCase>? _cases;
  List<VideoSummary> _videos = [];
  bool _admin = false;
  int? _selected;
  final _accepting = <int>{}; // [수락]을 누른 사건. 다시 누르지 못하게 막는다

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = ref.read(apiProvider);
    try {
      final admin = (await ref.read(meProvider.future)).isAdmin;
      final cases = await api.cases(); // 22
      var videos = <VideoSummary>[];
      try {
        videos = await api.videos(); // 8. 못 읽으면 초대 알림만 보인다
      } catch (_) {}
      refreshSession(ref); // 메뉴 배지 수도 다시 센다
      if (!mounted) return;
      setState(() {
        _admin = admin;
        _videos = videos;
        _cases = _ordered(cases);
        // 처음은 맨 위 사건이다(피해자는 수락할 초대가 있는 사건이 맨 위에 온다)
        if (_selected == null || !cases.any((c) => c.id == _selected)) {
          _selected = _cases!.firstOrNull?.id;
        }
      });
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    }
  }

  /// 피해자는 수락할 초대가, 관리자는 할 일이 있는 사건이 먼저이고, 그다음 최근에 연결한 사건 순이다.
  List<VideoCase> _ordered(List<VideoCase> cases) {
    bool first(VideoCase c) => _admin ? adminTodoCount(_videos.where((v) => v.caseId == c.id).toList()) > 0 : c.pending;
    return [...cases]..sort((a, b) {
      if (first(a) != first(b)) return first(a) ? -1 : 1;
      return b.createdAt.compareTo(a.createdAt);
    });
  }

  Future<void> _accept(VideoCase c) async {
    setState(() => _accepting.add(c.id));
    try {
      // 백엔드 연결 필요: 26번 사건 초대 수락 (D-233 초안)
      await backendNotice(context, ref, '수락');
      await ref.read(apiProvider).acceptCase(c.id); // 26
      if (!mounted) return;
      showMessage(context, '사건을 수락했습니다. 사건 목록에서 볼 수 있습니다.');
      await _load();
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _accepting.remove(c.id));
    }
  }

  /// 사건의 알림 (규칙은 notification_rules.dart).
  List<NoticeMessage> _messagesOf(VideoCase c) => messagesOf(c, _videos, admin: _admin);

  /// 왼쪽 목록 한 줄의 요약. 마지막 알림을 짧게 보인다 (캔버스 "사전 입력 필요 · …").
  String _summaryOf(VideoCase c) => switch (_messagesOf(c).last) {
    NoticeInvite() => c.pending ? (_admin ? '연결 요청 · 수락을 기다립니다' : '연결 요청 · 수락이 필요합니다') : '연결 수락 · 수락했습니다.',
    NoticeAccepted() => '연결 수락 · 수락했습니다.',
    NoticeStatus(:final chip, :final text) => '$chip · $text',
  };

  @override
  Widget build(BuildContext context) {
    final cases = _cases;
    if (cases == null) {
      return const PageFrame(
        current: NavItem.notifications,
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Center(child: CircularProgressIndicator()),
        ),
      );
    }
    if (cases.isEmpty) {
      return const PageFrame(
        current: NavItem.notifications,
        title: '알림',
        child: StateCard(icon: Icons.notifications_none, title: '새 알림이 없습니다'),
      );
    }
    final selected = cases.firstWhere((c) => c.id == _selected, orElse: () => cases.first);
    final list = _CaseList(
      cases: cases,
      selectedId: selected.id,
      caseTitleOf: (c) => _caseTitle(c, admin: _admin),
      summaryOf: _summaryOf,
      onSelect: (c) => setState(() => _selected = c.id),
    );
    final talk = _Conversation(
      videoCase: selected,
      admin: _admin,
      messages: _messagesOf(selected),
      accepting: _accepting.contains(selected.id),
      onAccept: () => _accept(selected),
    );
    return PageFrame(
      current: NavItem.notifications,
      child: isNarrow(context)
          ? Column(crossAxisAlignment: CrossAxisAlignment.stretch, spacing: 24, children: [list, talk])
          : Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(width: 340, child: list),
                const SizedBox(width: 40),
                Expanded(child: talk),
              ],
            ),
    );
  }
}

/// 사건 이름. 이름이 없는 사건(지금 백엔드)은 상대 이름으로 부른다.
String _caseTitle(VideoCase c, {required bool admin}) => c.name ?? '${admin ? c.victimName : c.adminName ?? '관리자'}의 사건';

class _CaseList extends StatelessWidget {
  const _CaseList({
    required this.cases,
    required this.selectedId,
    required this.caseTitleOf,
    required this.summaryOf,
    required this.onSelect,
  });

  final List<VideoCase> cases;
  final int selectedId;
  final String Function(VideoCase) caseTitleOf;
  final String Function(VideoCase) summaryOf;
  final ValueChanged<VideoCase> onSelect;

  @override
  Widget build(BuildContext context) => Semantics(
    label: '사건 목록',
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 6,
      children: [
        const Padding(
          padding: EdgeInsets.only(bottom: 8),
          child: Text('사건', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
        ),
        for (final c in cases)
          Material(
            color: c.id == selectedId ? lineColor : offWhiteColor,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: lineColor),
            ),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: () => onSelect(c),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 6,
                  children: [
                    Row(
                      spacing: 8,
                      children: [
                        Expanded(
                          child: Text(
                            caseTitleOf(c),
                            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                          ),
                        ),
                        SmallText(formatKstMinute(c.createdAt).substring(5)), // "MM-DD HH:mm"
                      ],
                    ),
                    Text(summaryOf(c), style: const TextStyle(fontSize: 13, color: subColor, height: 1.5)),
                  ],
                ),
              ),
            ),
          ),
      ],
    ),
  );
}

class _Conversation extends StatelessWidget {
  const _Conversation({
    required this.videoCase,
    required this.admin,
    required this.messages,
    required this.accepting,
    required this.onAccept,
  });

  final VideoCase videoCase;
  final bool admin;
  final List<NoticeMessage> messages;
  final bool accepting;
  final VoidCallback onAccept;

  @override
  Widget build(BuildContext context) {
    final c = videoCase;
    final adminName = c.adminName ?? '관리자';
    final title = _caseTitle(c, admin: admin);
    final state = c.pending ? '수락 대기 중' : '연결됨';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 12,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
            SmallText(admin ? '피해자 ${c.victimName} · $state' : '$adminName · $state'),
          ],
        ),
        Align(child: SmallText(formatKstDate(c.createdAt))),
        for (final m in messages)
          switch (m) {
            NoticeAccepted() => _Bubble(
              children: [
                Text(
                  '${c.victimName}님이 연결을 수락했습니다.',
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                ),
                SmallText(formatKstMinute(c.acceptedAt ?? c.createdAt)),
              ],
            ),
            NoticeInvite() => _Bubble(
              children: [
                Text(
                  admin ? '${c.victimName}님에게 사건 관계자 연결을 요청했습니다.' : '$adminName이 사건 관계자 연결을 요청했습니다.',
                  style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
                ),
                Text('사건 $title', style: const TextStyle(fontSize: 14, color: noteColor)),
                if (admin)
                  const SizedBox.shrink()
                else if (c.pending)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: FilledButton(
                      onPressed: accepting ? null : onAccept,
                      style: FilledButton.styleFrom(
                        minimumSize: const Size(0, 38),
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                      ),
                      child: const Text('수락'),
                    ),
                  )
                else
                  const Text('수락했습니다.', style: TextStyle(fontSize: 14, color: subColor)),
                SmallText(formatKstMinute(admin ? c.createdAt : c.acceptedAt ?? c.createdAt)),
              ],
            ),
            NoticeStatus(:final video, :final chip, :final text, :final problem) => _Bubble(
              onTap: () => context.go('/videos/${video.videoId}'),
              children: [
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      height: 28,
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      decoration: BoxDecoration(
                        color: problem ? failChipColor : pointColor,
                        borderRadius: BorderRadius.circular(14),
                      ),
                      alignment: Alignment.center,
                      child: Text(
                        chip,
                        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: offWhiteColor),
                      ),
                    ),
                  ],
                ),
                Text(text, style: const TextStyle(fontSize: 15)),
              ],
            ),
          },
      ],
    );
  }
}

/// 대화 말풍선 (캔버스: 최대 폭 520, 모서리 16, 옅은 그림자).
class _Bubble extends StatelessWidget {
  const _Bubble({required this.children, this.onTap});

  final List<Widget> children;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => ConstrainedBox(
    constraints: const BoxConstraints(maxWidth: 520),
    child: Material(
      color: offWhiteColor,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(cardRadius),
        side: const BorderSide(color: lineColor),
      ),
      shadowColor: const Color(0x0F2D3748),
      elevation: 1,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, spacing: 6, children: children),
        ),
      ),
    ),
  );
}
