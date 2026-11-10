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

/// 대화 한 칸. 사건 초대이거나, 영상 상태에서 만든 알림이다 (D-237).
sealed class _Message {
  const _Message();
}

class _InviteMessage extends _Message {
  const _InviteMessage(this.videoCase);

  final VideoCase videoCase;
}

class _StatusMessage extends _Message {
  const _StatusMessage(this.video, this.chip, this.text);

  final VideoSummary video;
  final String chip;
  final String text;
}

/// 영상 상태 중 피해자가 알아야 하는 것만 알림으로 만든다. 나머지(업로드·대기·분석 중)는 null.
_StatusMessage? _statusMessageOf(VideoSummary v) {
  if (v.maskedDeleted) return null;
  return switch (v.status) {
    VideoStatus.stage1Done => _StatusMessage(v, '사전 입력 필요', '${v.originalFilename} 차량과 파손 부위를 입력해 주세요.'),
    VideoStatus.ready || VideoStatus.batchRunning => _StatusMessage(v, '분석 완료', '결과는 주차장 관리자 화면에서 관리자와 함께 확인합니다.'),
    VideoStatus.finished || VideoStatus.exhausted => _StatusMessage(v, '확인 완료', '고정한 사건 지점의 시간을 볼 수 있습니다.'),
    VideoStatus.failed => _StatusMessage(v, '분석 실패', '${v.originalFilename} 영상을 분석하지 못했습니다. 관리자에게 문의해 주세요.'),
    _ => null,
  };
}

/// 2.11 알림 (피해자). 왼쪽은 사건, 오른쪽은 고른 사건의 알림 대화다 (캔버스, D-237).
/// 대기 중인 사건 초대는 [수락]하면 그 사건이 묶인다 (D-233). 거절과 메시지 보내기는 없다.
/// 22번·8번은 열 때와 [수락] 뒤에만 부른다. 주기적으로 부르지 않는다.
class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});

  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends ConsumerState<NotificationsPage> {
  List<VideoCase>? _cases;
  List<VideoSummary> _videos = [];
  int? _selected;
  final _accepting = <int>{}; // [수락]을 누른 사건. 다시 누르지 못하게 막는다

  @override
  void initState() {
    super.initState();
    // 관리자 계정은 알림이 없다. 피해자가 연결 화면을 열 때와 같이 목록으로 보낸다
    ref
        .read(meProvider.future)
        .then(
          (me) {
            if (me.isAdmin && mounted) redirectTo(context, '/videos');
          },
          onError: (Object e) {
            if (mounted) handleCommonError(context, e);
          },
        );
    _load();
  }

  Future<void> _load() async {
    final api = ref.read(apiProvider);
    try {
      final cases = await api.cases(); // 22
      var videos = <VideoSummary>[];
      try {
        videos = await api.videos(); // 8. 못 읽으면 초대 알림만 보인다
      } catch (_) {}
      refreshSession(ref); // 메뉴 배지 수도 다시 센다
      if (!mounted) return;
      setState(() {
        _cases = _ordered(cases);
        _videos = videos;
        // 처음은 수락할 초대가 있는 사건, 없으면 맨 위 사건을 고른다
        if (_selected == null || !cases.any((c) => c.id == _selected)) {
          _selected = (cases.where((c) => c.pending).firstOrNull ?? _cases!.firstOrNull)?.id;
        }
      });
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    }
  }

  /// 수락할 초대가 먼저, 그다음 최근에 연결한 사건 순이다.
  List<VideoCase> _ordered(List<VideoCase> cases) => [...cases]
    ..sort((a, b) {
      if (a.pending != b.pending) return a.pending ? -1 : 1;
      return b.createdAt.compareTo(a.createdAt);
    });

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

  /// 사건의 알림. 초대가 먼저이고, 수락한 사건만 영상 상태 알림이 붙는다.
  List<_Message> _messagesOf(VideoCase c) => [
    _InviteMessage(c),
    if (!c.pending)
      for (final v in _videos)
        if (v.caseId == c.id) ?_statusMessageOf(v),
  ];

  /// 왼쪽 목록 한 줄의 요약. 마지막 알림을 짧게 보인다 (캔버스 "사전 입력 필요 · …").
  String _summaryOf(VideoCase c) => switch (_messagesOf(c).last) {
    _InviteMessage() => c.pending ? '연결 요청 · 수락이 필요합니다' : '연결 수락 · 수락했습니다.',
    _StatusMessage(:final chip, :final text) => '$chip · $text',
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
      summaryOf: _summaryOf,
      onSelect: (c) => setState(() => _selected = c.id),
    );
    final talk = _Conversation(
      videoCase: selected,
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

/// 사건 이름. 이름이 없는 사건(지금 백엔드)은 관리자 이름으로 부른다.
String _caseTitle(VideoCase c) => c.name ?? '${c.adminName ?? '관리자'}의 사건';

class _CaseList extends StatelessWidget {
  const _CaseList({required this.cases, required this.selectedId, required this.summaryOf, required this.onSelect});

  final List<VideoCase> cases;
  final int selectedId;
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
                          child: Text(_caseTitle(c), style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
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
    required this.messages,
    required this.accepting,
    required this.onAccept,
  });

  final VideoCase videoCase;
  final List<_Message> messages;
  final bool accepting;
  final VoidCallback onAccept;

  @override
  Widget build(BuildContext context) {
    final c = videoCase;
    final admin = c.adminName ?? '관리자';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 12,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_caseTitle(c), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
            SmallText('$admin · ${c.pending ? '수락 대기 중' : '연결됨'}'),
          ],
        ),
        Align(child: SmallText(formatKstDate(c.createdAt))),
        for (final m in messages)
          switch (m) {
            _InviteMessage() => _Bubble(
              children: [
                Text('$admin이 사건 관계자 연결을 요청했습니다.', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                Text('사건 ${_caseTitle(c)}', style: const TextStyle(fontSize: 14, color: noteColor)),
                if (c.pending)
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
                SmallText(formatKstMinute(c.acceptedAt ?? c.createdAt)),
              ],
            ),
            _StatusMessage(:final video, :final chip, :final text) => _Bubble(
              onTap: () => context.go('/videos/${video.videoId}'),
              children: [
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      height: 28,
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      decoration: BoxDecoration(color: pointColor, borderRadius: BorderRadius.circular(14)),
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
