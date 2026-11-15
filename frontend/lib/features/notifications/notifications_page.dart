import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/format.dart';
import '../../core/constants.dart';
import '../../core/models/account.dart';
import '../../core/models/message.dart';
import '../../core/models/video.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';
import 'chat_rules.dart';
import 'notification_rules.dart';

/// 2.11 채팅 (두 계정). 왼쪽은 상대 계정(관리자 화면은 피해자, 피해자 화면은 관리자),
/// 오른쪽은 고른 사람과의 대화로, 사건마다 구분선 아래에 그 사건의 알림을 잇는다.
/// 대기 중인 사건 초대는 피해자가 [수락]하면 그 사건이 묶인다 (D-233). 관리자는 [수락]이 없고 할 일을 본다 (D-243).
/// 거절은 없다. 대화 아래에 메시지 흐름과 입력칸이 있고, 수락한 사건이 있는 상대에게만 보낸다 (D-294).
/// 22번·8번·메시지는 열 때와 [수락]·보내기 뒤에만 읽는다. 새 메시지 받기(WebSocket, D-286)는 05장 주소가 나오면 붙인다.
class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});

  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsPageState();
}

/// 한 상대 계정과 묶인 사건들. 22번에 상대 계정 ID가 없어 지금은 이름으로 묶는다.
class _Person {
  _Person(this.name, this.cases);

  final String name;

  /// 오래된 사건부터 (대화는 위에서 아래로 시간 순).
  final List<VideoCase> cases;

  String get latestAt => cases.last.createdAt;
}

class _NotificationsPageState extends ConsumerState<NotificationsPage> {
  List<_Person>? _people;
  List<VideoSummary> _videos = [];
  bool _admin = false;
  Me? _me;
  List<ChatMessage> _chat = [];
  bool _sending = false;
  final _input = TextEditingController();
  String? _selected;
  final _accepting = <int>{}; // [수락]을 누른 사건. 다시 누르지 못하게 막는다

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  /// 채팅 메시지 읽기 (D-286 지난 메시지 조회, 주소는 05장 미정). 못 읽으면 조용히 비워 둔다(서버에 아직 없을 수 있다).
  Future<void> _loadMessages() async {
    try {
      final chat = await ref.read(apiProvider).messages();
      if (mounted) setState(() => _chat = chat);
    } catch (_) {}
  }

  /// 메시지 보내기 (D-286). 지금 임시 API가 사건 번호를 받아 그 사람과의 최근 수락 사건 번호를 넘긴다.
  Future<void> _send(VideoCase target) async {
    final text = _input.text.trim();
    if (text.isEmpty || text.length > maxMessageLength || _sending) return;
    setState(() => _sending = true);
    try {
      await ref.read(apiProvider).sendMessage(target.id, text);
      if (!mounted) return;
      _input.clear();
      await _loadMessages();
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _load() async {
    final api = ref.read(apiProvider);
    try {
      final me = await ref.read(meProvider.future);
      final admin = me.isAdmin;
      final cases = await api.cases(); // 22
      var videos = <VideoSummary>[];
      try {
        videos = await api.videos(); // 8. 못 읽으면 초대 알림만 보인다
      } catch (_) {}
      refreshSession(ref); // 메뉴 배지 수도 다시 센다
      await _loadMessages();
      if (!mounted) return;
      setState(() {
        _admin = admin;
        _me = me;
        _videos = videos;
        final people = _grouped(cases);
        _people = people;
        // 처음은 맨 위 사람이다(피해자는 수락할 초대가 있는 관리자가 맨 위에 온다)
        if (_selected == null || !people.any((p) => p.name == _selected)) {
          _selected = people.firstOrNull?.name;
        }
      });
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    }
  }

  String _nameOf(VideoCase c) => _admin ? c.victimName : c.adminName ?? '관리자';

  /// 피해자는 수락할 초대가, 관리자는 할 일이 있는 사건인지.
  bool _needsAction(VideoCase c) =>
      _admin ? adminTodoCount(_videos.where((v) => v.caseId == c.id).toList()) > 0 : c.pending;

  /// 상대 계정별로 묶는다. 할 일이 있는 사람이 먼저이고, 그다음 최근에 연결한 사람 순이다.
  List<_Person> _grouped(List<VideoCase> cases) {
    final byName = <String, List<VideoCase>>{};
    for (final c in cases) {
      byName.putIfAbsent(_nameOf(c), () => []).add(c);
    }
    final people = [
      for (final e in byName.entries) _Person(e.key, e.value..sort((a, b) => a.createdAt.compareTo(b.createdAt))),
    ];
    bool first(_Person p) => p.cases.any(_needsAction);
    return people..sort((a, b) {
      if (first(a) != first(b)) return first(a) ? -1 : 1;
      return b.latestAt.compareTo(a.latestAt);
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

  /// 사건 한 건의 요약. 마지막 알림을 짧게 보인다 (캔버스 "사전 입력 필요 · …").
  String _caseSummary(VideoCase c) => switch (_messagesOf(c).last) {
    NoticeInvite() => c.pending ? (_admin ? '연결 요청 · 수락을 기다립니다' : '연결 요청 · 수락이 필요합니다') : '연결 수락 · 수락했습니다.',
    NoticeAccepted() => '연결 수락 · 수락했습니다.',
    NoticeStatus(:final chip, :final title) => '$chip · $title',
  };

  /// 왼쪽 목록 한 줄의 요약. 할 일이 있는 최근 사건, 없으면 최근 사건의 마지막 알림이다.
  String _summaryOf(_Person p) {
    final c = p.cases.reversed.firstWhere(_needsAction, orElse: () => p.cases.last);
    final summary = _caseSummary(c);
    return p.cases.length > 1 ? '사건 ${p.cases.length}건 · $summary' : summary;
  }

  @override
  Widget build(BuildContext context) {
    final people = _people;
    if (people == null) {
      return const PageFrame(
        current: NavItem.notifications,
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Center(child: CircularProgressIndicator()),
        ),
      );
    }
    if (people.isEmpty) {
      return const PageFrame(
        current: NavItem.notifications,
        title: '채팅',
        child: StateCard(icon: Icons.notifications_none, title: '새 알림이 없습니다'),
      );
    }
    final selected = people.firstWhere((p) => p.name == _selected, orElse: () => people.first);
    final list = _PersonList(
      admin: _admin,
      people: people,
      selectedName: selected.name,
      summaryOf: _summaryOf,
      onSelect: (p) => setState(() => _selected = p.name),
    );
    final talk = _Conversation(
      person: selected,
      admin: _admin,
      messagesOf: _messagesOf,
      accepting: _accepting,
      onAccept: _accept,
      chat: messagesOfPerson(selected.cases, _chat),
      me: _me,
      target: sendTargetOf(selected.cases),
      input: _input,
      sending: _sending,
      onSend: _send,
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

class _PersonList extends StatelessWidget {
  const _PersonList({
    required this.admin,
    required this.people,
    required this.selectedName,
    required this.summaryOf,
    required this.onSelect,
  });

  final bool admin;
  final List<_Person> people;
  final String selectedName;
  final String Function(_Person) summaryOf;
  final ValueChanged<_Person> onSelect;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '${admin ? '피해자' : '관리자'} 목록',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 6,
        children: [
          for (final p in people)
            Material(
              color: p.name == selectedName ? lineColor : offWhiteColor,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
                side: const BorderSide(color: lineColor),
              ),
              clipBehavior: Clip.antiAlias,
              child: InkWell(
                onTap: () => onSelect(p),
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
                            child: Text(p.name, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                          ),
                          SmallText(formatKstMinute(p.latestAt).substring(5)), // "MM-DD HH:mm"
                        ],
                      ),
                      Text(summaryOf(p), style: const TextStyle(fontSize: 13, color: subColor, height: 1.5)),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// 고른 사람과의 대화. 사건마다 날짜 구분선 아래에 그 사건의 알림을 잇는다.
class _Conversation extends StatelessWidget {
  const _Conversation({
    required this.person,
    required this.admin,
    required this.messagesOf,
    required this.accepting,
    required this.onAccept,
    required this.chat,
    required this.me,
    required this.target,
    required this.input,
    required this.sending,
    required this.onSend,
  });

  final _Person person;
  final bool admin;
  final List<NoticeMessage> Function(VideoCase) messagesOf;
  final Set<int> accepting;
  final ValueChanged<VideoCase> onAccept;
  final List<ChatMessage> chat;
  final Me? me;
  final VideoCase? target;
  final TextEditingController input;
  final bool sending;
  final ValueChanged<VideoCase> onSend;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: 12,
    children: [
      Text(person.name, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
      for (final c in person.cases) ..._caseMessages(context, c),
      const Divider(color: lineColor),
      for (final m in chat) _Bubble(message: m, mine: me != null && m.mine(me!)),
      _Composer(target: target, input: input, sending: sending, onSend: onSend),
    ],
  );

  List<Widget> _caseMessages(BuildContext context, VideoCase c) {
    final title = _caseTitle(c, admin: admin);
    return [
      Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Row(
          spacing: 12,
          children: [
            const Expanded(child: Divider(color: lineColor)),
            SmallText(formatKstDate(c.createdAt)), // 날짜는 짧으니 양쪽 선이 남는 폭을 반씩 채운다
            const Expanded(child: Divider(color: lineColor)),
          ],
        ),
      ),
      for (final m in messagesOf(c))
        switch (m) {
          NoticeAccepted() => _NoticeCard(
            title: acceptedTitle,
            emoji: acceptedEmoji,
            caseLine: '사건 $title',
            at: c.acceptedAt ?? c.createdAt,
          ),
          NoticeInvite() => _NoticeCard(
            title: inviteTitle(admin: admin),
            emoji: inviteEmoji,
            caseLine: '사건 $title',
            at: admin ? c.createdAt : c.acceptedAt ?? c.createdAt,
            footer: admin
                ? null
                : c.pending
                ? FilledButton(
                    onPressed: accepting.contains(c.id) ? null : () => onAccept(c),
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(0, 38),
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                    ),
                    child: const Text('수락'),
                  )
                : const Text('수락했습니다.', style: TextStyle(fontSize: 14, color: subColor)),
          ),
          NoticeStatus(:final video, :final title, :final emoji, :final problem) => _NoticeCard(
            title: title,
            emoji: emoji,
            problem: problem,
            caseLine: '사건 $title · ${video.originalFilename}',
            onTap: () => context.go('/videos/${video.videoId}'),
          ),
        },
    ];
  }
}

/// 알림 카드. 제목과 오른쪽 이모지, 아래 한 줄에 사건을 적는다.
/// [problem]이면 제목을 실패 색으로 그린다. [at]이 있으면 카드 오른쪽 아래 바깥에 시각(HH:mm)만 보인다.
class _NoticeCard extends StatelessWidget {
  const _NoticeCard({
    required this.title,
    required this.emoji,
    required this.caseLine,
    this.problem = false,
    this.footer,
    this.onTap,
    this.at,
  });

  final String title;
  final String emoji;
  final String caseLine;
  final bool problem;
  final Widget? footer;
  final VoidCallback? onTap;
  final String? at;

  @override
  Widget build(BuildContext context) {
    final time = at;
    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      spacing: 8,
      children: [
        Flexible(child: _box()),
        if (time != null) SmallText(formatKstMinute(time).substring(11)), // "HH:mm"
      ],
    );
  }

  Widget _box() => ConstrainedBox(
    constraints: const BoxConstraints(maxWidth: 320),
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
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            spacing: 6,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                spacing: 10,
                children: [
                  Expanded(
                    child: Text(
                      title,
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        height: 1.35,
                        color: problem ? failChipColor : null, // 실패 알림은 제목을 실패 색으로
                      ),
                    ),
                  ),
                  ExcludeSemantics(child: Text(emoji, style: const TextStyle(fontSize: 30))),
                ],
              ),
              Text(
                caseLine,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 13, color: noteColor),
              ),
              ?footer,
            ],
          ),
        ),
      ),
    ),
  );
}

/// 메시지 말풍선. 내 것은 오른쪽, 상대 것은 왼쪽이고 시각(HH:mm)을 옆에 붙인다 (D-294).
class _Bubble extends StatelessWidget {
  const _Bubble({required this.message, required this.mine});

  final ChatMessage message;
  final bool mine;

  @override
  Widget build(BuildContext context) {
    final time = SmallText(formatKstMinute(message.createdAt).substring(11)); // "HH:mm"
    final box = Flexible(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: mine ? pointColor : offWhiteColor,
            borderRadius: BorderRadius.circular(cardRadius),
            border: Border.all(color: mine ? pointColor : lineColor),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            child: Text(message.body, style: TextStyle(fontSize: 16, color: mine ? offWhiteColor : inkColor)),
          ),
        ),
      ),
    );
    return Row(
      mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.end,
      spacing: 8,
      children: mine ? [time, box] : [box, time],
    );
  }
}

/// 메시지 입력칸 + [보내기]. 수락한 사건이 없으면([target]이 null) 막고 안내한다 (D-294).
class _Composer extends StatelessWidget {
  const _Composer({required this.target, required this.input, required this.sending, required this.onSend});

  final VideoCase? target;
  final TextEditingController input;
  final bool sending;
  final ValueChanged<VideoCase> onSend;

  @override
  Widget build(BuildContext context) {
    final t = target;
    if (t == null) return const SmallText('사건을 수락하면 메시지를 보낼 수 있습니다.');
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 8,
      children: [
        Expanded(
          child: TextField(
            controller: input,
            maxLength: maxMessageLength,
            textInputAction: TextInputAction.send,
            onSubmitted: (_) => onSend(t), // Enter로 보내기
            decoration: const InputDecoration(hintText: '메시지를 입력하세요'),
          ),
        ),
        FilledButton(
          onPressed: sending ? null : () => onSend(t),
          style: FilledButton.styleFrom(minimumSize: const Size(0, 48)),
          child: const Text('보내기'),
        ),
      ],
    );
  }
}
