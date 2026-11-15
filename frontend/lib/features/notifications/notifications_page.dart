import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
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
/// 거절은 없다. 대화 아래에 메시지 흐름과 입력칸이 있고, 수락한 사건이 있는 상대에게만 보낸다 (D-297).
/// 22번·8번·메시지는 열 때와 [수락]·보내기 뒤에만 읽는다. 새 메시지 받기(WebSocket, D-286)는 05장 주소가 나오면 붙인다.
class NotificationsPage extends ConsumerStatefulWidget {
  const NotificationsPage({super.key});

  @override
  ConsumerState<NotificationsPage> createState() => _NotificationsPageState();
}

/// 한 상대 계정과 묶인 사건들. 22번에 상대 계정 ID가 없어 지금은 이름으로 묶고, 29번 대화 상대([peer])를 이름으로 짝짓는다.
/// 사건을 모두 숨긴 상대는 [cases]가 비고 [peer]만 있다. 수락한 사건이 없어 29번에 없는 상대는 [peer]가 null이다 (D-298).
class _Person {
  _Person(this.name, this.cases, this.peer);

  final String name;

  /// 오래된 사건부터 (대화는 위에서 아래로 시간 순).
  final List<VideoCase> cases;
  final ChatPeer? peer;

  /// 목록에 보일 가장 최근 시각. 사건이 있으면 연결 시각, 없으면 마지막 메시지 시각이다.
  String? get latestAt => cases.isNotEmpty ? cases.last.createdAt : peer?.lastMessage?.createdAt;
}

class _NotificationsPageState extends ConsumerState<NotificationsPage> {
  List<VideoCase>? _cases; // 22번. null이면 아직 읽는 중
  List<ChatPeer> _peers = []; // 29번
  List<VideoSummary> _videos = [];
  bool _admin = false;
  List<ChatMessage> _chat = []; // 고른 사람과의 최근 메시지 (30번)
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

  /// 29번 대화 목록. 못 읽으면(서버에 아직 없을 수 있다) 비워 두고 알림 카드는 그대로 보인다.
  Future<void> _loadPeers() async {
    var peers = <ChatPeer>[];
    try {
      peers = (await ref.read(apiProvider).chats()).items; // 29
    } catch (_) {}
    if (mounted) setState(() => _peers = peers);
  }

  /// 고른 사람의 최근 메시지를 읽고(30번), 화면에 그린 뒤 읽음으로 알린다(32번) (D-298).
  Future<void> _openChat(String? name) async {
    final peer = name == null ? null : peerOf(name, _peers);
    if (peer == null) {
      if (mounted) setState(() => _chat = []);
      return;
    }
    try {
      final messages = await ref.read(apiProvider).chatMessages(peer.peerUserId); // 30
      if (!mounted || _selected != name) return; // 그 사이 다른 사람을 골랐다
      setState(() => _chat = messages);
      WidgetsBinding.instance.addPostFrameCallback((_) => _markRead(peer, messages));
    } catch (e) {
      if (!mounted) return;
      if (e is ApiException && e.code == 'CHAT_NOT_FOUND') {
        await _loadPeers(); // 없는 대화다. 목록을 새로 그린다 (D-287)
      } else {
        handleCommonError(context, e);
      }
    }
  }

  /// 보인 메시지 중 가장 큰 id까지 읽음으로 알린다. 실패하면 조용히 넘어간다(다음에 열 때 다시 처리, D-289).
  Future<void> _markRead(ChatPeer peer, List<ChatMessage> shown) async {
    if (shown.isEmpty) return;
    final lastId = shown.map((m) => m.id).reduce((a, b) => a > b ? a : b);
    try {
      await ref.read(apiProvider).markChatRead(peer.peerUserId, lastId); // 32
    } catch (_) {
      return;
    }
    await _loadPeers();
    if (mounted) ref.invalidate(notificationBadgeProvider); // 읽음 처리 뒤 메뉴 배지를 다시 센다 (D-298)
  }

  void _select(_Person p) {
    setState(() => _selected = p.name);
    _openChat(p.name);
  }

  /// 메시지 보내기 (31번). 응답 메시지를 대화에 합치고, 목록 요약을 위해 29번을 다시 읽는다.
  Future<void> _send(ChatPeer peer) async {
    final text = _input.text.trim();
    if (text.isEmpty || text.length > maxMessageLength || _sending) return;
    setState(() => _sending = true);
    try {
      final sent = await ref.read(apiProvider).sendChat(peer.peerUserId, text); // 31
      if (!mounted) return;
      _input.clear();
      final current = _selected == null ? null : peerOf(_selected!, _peers);
      if (current?.peerUserId == peer.peerUserId) setState(() => _chat = mergeMessages(_chat, [sent]));
      await _loadPeers();
    } catch (e) {
      if (!mounted) return;
      if (e is ApiException && e.code == 'CHAT_NOT_FOUND') {
        await _loadPeers();
      } else {
        handleCommonError(context, e);
      }
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
      var peers = <ChatPeer>[];
      try {
        peers = (await api.chats()).items; // 29. 못 읽으면 채팅 부분만 빈다
      } catch (_) {}
      refreshSession(ref); // 메뉴 배지 수도 다시 센다
      if (!mounted) return;
      setState(() {
        _admin = admin;
        _videos = videos;
        _cases = cases;
        _peers = peers;
        final people = _grouped();
        // 처음은 맨 위 사람이다(피해자는 수락할 초대가 있는 관리자가 맨 위에 온다)
        if (_selected == null || !people.any((p) => p.name == _selected)) {
          _selected = people.firstOrNull?.name;
        }
      });
      await _openChat(_selected);
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    }
  }

  String _nameOf(VideoCase c) => _admin ? c.victimName : c.adminName ?? '관리자';

  /// 피해자는 수락할 초대가, 관리자는 할 일이 있는 사건인지.
  bool _needsAction(VideoCase c) =>
      _admin ? adminTodoCount(_videos.where((v) => v.caseId == c.id).toList()) > 0 : c.pending;

  /// 상대 계정별로 묶는다. 할 일이 있는 사람이 먼저이고, 그다음 최근 시각 순이다.
  /// 29번에만 있는 상대(사건을 모두 숨긴 경우)도 한 줄로 붙인다 (D-298).
  List<_Person> _grouped() {
    final byName = <String, List<VideoCase>>{};
    for (final c in _cases ?? <VideoCase>[]) {
      byName.putIfAbsent(_nameOf(c), () => []).add(c);
    }
    for (final p in _peers) {
      byName.putIfAbsent(p.peerName, () => []);
    }
    final people = [
      for (final e in byName.entries)
        _Person(e.key, e.value..sort((a, b) => a.createdAt.compareTo(b.createdAt)), peerOf(e.key, _peers)),
    ];
    bool first(_Person p) => p.cases.any(_needsAction);
    return people..sort((a, b) {
      if (first(a) != first(b)) return first(a) ? -1 : 1;
      return (b.latestAt ?? '').compareTo(a.latestAt ?? '');
    });
  }

  Future<void> _accept(VideoCase c) async {
    setState(() => _accepting.add(c.id));
    try {
      // 26번 사건 초대 수락 (D-233). 데모에서는 다른 버튼처럼 "눌렀다" 팝업을 먼저 띄운다
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

  /// 왼쪽 목록 한 줄의 요약: "가장 최근 알림 · 가장 최근 채팅" (D-297).
  /// 알림은 가장 최근 사건의 마지막 알림을 짧은 상태 이름으로, 채팅은 29번의 마지막 메시지 내용 전부다. 없는 쪽은 뺀다.
  String _summaryOf(_Person p) {
    final notice = p.cases.isEmpty ? null : noticeLabel(_messagesOf(p.cases.last).last);
    final chat = p.peer?.lastMessage?.body;
    return [?notice, ?chat].join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    if (_cases == null) {
      return const PageFrame(
        current: NavItem.notifications,
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Center(child: CircularProgressIndicator()),
        ),
      );
    }
    final people = _grouped();
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
      onSelect: _select,
    );
    final talk = _Conversation(
      person: selected,
      admin: _admin,
      messagesOf: _messagesOf,
      accepting: _accepting,
      onAccept: _accept,
      chat: _chat,
      peer: selected.peer,
      input: _input,
      sending: _sending,
      onSend: _send,
    );
    // 본문 전체를 스크롤하지 않고 창 높이에 맞춘다. 목록과 대화가 각자 스크롤하고, 입력칸은 아래에 고정된다 (D-297)
    final scrollList = SingleChildScrollView(child: list);
    return PageFrame(
      current: NavItem.notifications,
      scrollBody: false,
      child: isNarrow(context)
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              spacing: 16,
              children: [
                ConstrainedBox(constraints: const BoxConstraints(maxHeight: 180), child: scrollList),
                Expanded(child: talk),
              ],
            )
          : Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(width: 280, child: scrollList),
                const SizedBox(width: 32),
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
          // 어느 상대를 골라도 항상 보이게 목록 위에 둔다 (D-288, D-298)
          const Padding(padding: EdgeInsets.only(bottom: 4), child: SmallText('메시지는 보낸 지 30일이 지나면 지워집니다.')),
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
                          if (p.latestAt case final at?) SmallText(formatKstMinute(at).substring(5)), // "MM-DD HH:mm"
                        ],
                      ),
                      // 시간 아래까지 한 줄을 쓰고, 넘치면 "..."로 줄인다. 안 읽은 수는 그 줄 오른쪽 끝에 둔다 (D-297, D-298)
                      Row(
                        spacing: 8,
                        children: [
                          Expanded(
                            child: Text(
                              summaryOf(p),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 13, color: subColor, height: 1.5),
                            ),
                          ),
                          if ((p.peer?.unread ?? 0) > 0) _UnreadDot(p.peer!.unread),
                        ],
                      ),
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

/// 안 읽은 메시지 수를 보이는 빨간 숫자 동그라미 (D-298).
class _UnreadDot extends StatelessWidget {
  const _UnreadDot(this.count);

  final int count;

  @override
  Widget build(BuildContext context) => Semantics(
    label: '안 읽은 메시지 $count개',
    child: Container(
      constraints: const BoxConstraints(minWidth: 20, minHeight: 20),
      padding: const EdgeInsets.symmetric(horizontal: 6),
      alignment: Alignment.center,
      decoration: const BoxDecoration(color: failChipColor, borderRadius: BorderRadius.all(Radius.circular(10))),
      child: Text('$count', style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: offWhiteColor)),
    ),
  );
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
    required this.peer,
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

  /// 29번의 이 사람. null이면 수락한 사건이 없어 보낼 수 없다.
  final ChatPeer? peer;
  final TextEditingController input;
  final bool sending;
  final ValueChanged<ChatPeer> onSend;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    spacing: 12,
    children: [
      Text(person.name, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
      // 대화만 스크롤하고 입력칸은 아래에 고정한다. reverse라 처음부터 맨 아래(최근 메시지)가 보인다 (D-297)
      Expanded(
        child: SingleChildScrollView(
          reverse: true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            spacing: 12,
            children: [
              for (final c in person.cases) ..._caseMessages(context, c),
              const Divider(color: lineColor),
              for (final m in chat) _Bubble(message: m, mine: m.mine),
            ],
          ),
        ),
      ),
      _Composer(peer: peer, input: input, sending: sending, onSend: onSend),
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
            title: acceptedTitle(admin: admin),
            emoji: acceptedEmoji,
            caseLine: title,
            mine: noticeIsMine(m, admin: admin),
            at: c.acceptedAt ?? c.createdAt,
          ),
          NoticeInvite() => _NoticeCard(
            title: inviteTitle(admin: admin),
            emoji: inviteEmoji,
            caseLine: title,
            mine: noticeIsMine(m, admin: admin),
            at: c.createdAt,
            // 수락하면 오른쪽에 수락 카드가 따로 붙으므로, 요청 카드에는 수락 전 [수락]만 둔다
            footer: !admin && c.pending
                ? FilledButton(
                    onPressed: accepting.contains(c.id) ? null : () => onAccept(c),
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(0, 38),
                      padding: const EdgeInsets.symmetric(horizontal: 16),
                    ),
                    child: const Text('수락'),
                  )
                : null,
          ),
          NoticeStatus(:final video, title: final noticeTitle, :final emoji, :final problem) => _NoticeCard(
            title: noticeTitle,
            emoji: emoji,
            problem: problem,
            caseLine: title, // 작은 글씨는 사건 이름만 (D-297)
            mine: noticeIsMine(m, admin: admin),
            onTap: () => context.go('/videos/${video.videoId}'),
          ),
        },
    ];
  }
}

/// 알림 카드. 제목과 오른쪽 이모지, 아래 작은 글씨로 사건 이름만 적는다.
/// [problem]이면 제목을 실패 색으로 그린다. [mine]이면(내가 한 일) 오른쪽, 아니면 왼쪽에 둔다 (D-297).
/// [at]이 있으면 카드 바깥 안쪽 옆에 시각(HH:mm)만 보인다.
class _NoticeCard extends StatelessWidget {
  const _NoticeCard({
    required this.title,
    required this.emoji,
    required this.caseLine,
    this.problem = false,
    this.footer,
    this.onTap,
    this.at,
    required this.mine,
  });

  final String title;
  final String emoji;
  final String caseLine;
  final bool mine;
  final bool problem;
  final Widget? footer;
  final VoidCallback? onTap;
  final String? at;

  @override
  Widget build(BuildContext context) {
    final time = at;
    final stamp = time == null ? null : SmallText(formatKstMinute(time).substring(11)); // "HH:mm"
    final box = Flexible(child: _box());
    return Row(
      mainAxisAlignment: mine ? MainAxisAlignment.end : MainAxisAlignment.start,
      crossAxisAlignment: CrossAxisAlignment.end,
      spacing: 8,
      children: mine ? [?stamp, box] : [box, ?stamp],
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
            spacing: 2, // 제목과 사건 이름을 붙인다 (D-297)
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
                  ExcludeSemantics(child: Text(emoji, style: const TextStyle(fontSize: 20, height: 1.2))),
                ],
              ),
              Text(
                caseLine,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 13, color: noteColor),
              ),
              if (footer case final f?) Padding(padding: const EdgeInsets.only(top: 8), child: f), // [수락]은 조금 띄운다
            ],
          ),
        ),
      ),
    ),
  );
}

/// 메시지 말풍선. 내 것은 오른쪽, 상대 것은 왼쪽이고 시각(HH:mm)을 옆에 붙인다 (D-297).
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
            color: mine ? pointLightColor : offWhiteColor, // 내 것은 연한 포인트색 (D-297)
            borderRadius: BorderRadius.circular(cardRadius),
            border: Border.all(color: mine ? pointLightColor : lineColor),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            child: Text(message.body, style: const TextStyle(fontSize: 16, color: inkColor)),
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

/// 메시지 입력칸 + [보내기]. 수락한 사건이 없으면([peer]가 null) 막고 안내한다 (D-297).
class _Composer extends StatelessWidget {
  const _Composer({required this.peer, required this.input, required this.sending, required this.onSend});

  final ChatPeer? peer;
  final TextEditingController input;
  final bool sending;
  final ValueChanged<ChatPeer> onSend;

  @override
  Widget build(BuildContext context) {
    final t = peer;
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
