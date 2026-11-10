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
import '../cases/case_link_page.dart' show caseNameEmptyMessage, caseNameMaxLength;

/// 표 머리를 눌러 고르는 정렬 (D-211). 화면에서만 정렬하고 8번을 다시 부르지 않는다.
/// [uploaded]는 처음 정렬(업로드 날짜 최신순)이다. 칸은 없고, 이때 표 머리는 모두 위아래 화살표다 (캔버스 메모, D-237).
enum ListSort { name, person, status, expires, uploaded }

/// 표 머리 칸과 그 칸의 정렬. 업로드 날짜 칸은 없앴다 (D-237).
const _headerSorts = [ListSort.name, ListSort.person, ListSort.status, ListSort.expires];

// 표 칸 비율: 사건 이름 · 피해자(관리자) · 상태 · 열람기한 (캔버스 2.2). 그 뒤에 삭제 아이콘 칸이 붙는다
const _columnFlex = [30, 14, 15, 12];
const _deleteColumnWidth = 48.0;

/// 네 칸 표를 펼칠 최소 창 폭. 이보다 좁으면 칸이 모자라 칩이 넘치므로,
/// 좁은 창처럼 사건 이름 아래에 접어 보인다.
const _tableMinWidth = 960.0;

bool _folded(BuildContext context) => MediaQuery.sizeOf(context).width < _tableMinWidth;

/// 칸 안 내용이 칸보다 넓으면 줄바꿈·넘침 대신 조금 줄여 보인다.
Widget _fit(Widget child) => FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: child);

/// 목록 한 줄. 영상이거나, 영상을 아직 올리지 않은 사건이다 (D-211, D-226).
class ListRow {
  ListRow.video(VideoSummary this.video, this.videoCase);
  ListRow.emptyCase(VideoCase this.videoCase) : video = null;

  final VideoSummary? video;
  final VideoCase? videoCase;

  /// 보이는 사건 이름. 이름이 없는 사건(지금 백엔드)은 영상 파일 이름, 그것도 없으면 "—" (캔버스, D-237).
  String get name => videoCase?.name ?? video?.originalFilename ?? '—';

  /// 사건 이름 아래 작게 보일 영상 파일 이름. 한 사건에 영상이 여럿이면 줄을 구분한다.
  String? get filename => videoCase?.name == null ? null : video?.originalFilename;

  /// 피해자가 아직 초대를 수락하지 않은 사건의 줄 (D-233). 관리자 목록에서만 "수락 대기 중"으로 보인다.
  bool get pending => videoCase?.pending ?? false;

  /// 업로드 날짜. 영상 없는 사건은 연결한 날로 정렬한다.
  String? get uploadedAt => video?.createdAt ?? videoCase?.createdAt;
}

/// 검색. 보이는 사건 이름에 [query]가 들어 있는 줄만 남긴다. 대소문자와 앞뒤 공백은 가리지 않는다 (D-237).
List<ListRow> searchRows(List<ListRow> rows, String query) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return rows;
  return [
    for (final r in rows)
      if (r.name.toLowerCase().contains(q)) r,
  ];
}

/// 정렬. 사건 이름·상대 이름은 가나다순, 상태는 할 일이 먼저, 업로드 날짜는 최신순, 열람기한은 가까운 순이다.
/// 같으면 받은 순서(최신순)를 지킨다. Dart의 List.sort는 안정 정렬이 아니라서 원래 위치를 함께 비교한다.
List<ListRow> sortRows(List<ListRow> rows, ListSort sort, {required bool admin}) {
  // 상태 순위: 업로드 필요·사전 입력 필요 0 → 후보 선택 가능 1 → 문제 2 → 기다림 3 → 완료 4 → 종료됨 5
  int rank(ListRow r) {
    if (r.pending) return 3; // 수락 대기 중은 기다림 (D-233)
    final v = r.video;
    if (v == null) return admin ? 0 : 3; // 관리자는 할 일, 피해자는 기다림 (D-226)
    return switch (v.listGroup(admin: admin)) {
      StatusGroup.ended => 5,
      StatusGroup.todo => v.status == VideoStatus.stage1Done ? 0 : 1,
      StatusGroup.problem => 2,
      StatusGroup.waiting => 3,
      StatusGroup.done => 4,
    };
  }

  String person(ListRow r) => (admin ? r.videoCase?.victimName : r.videoCase?.adminName) ?? '';
  int compare(ListRow a, ListRow b) => switch (sort) {
    ListSort.name => a.name.compareTo(b.name),
    ListSort.person => person(a).compareTo(person(b)),
    ListSort.status => rank(a).compareTo(rank(b)),
    ListSort.uploaded => (b.uploadedAt ?? '').compareTo(a.uploadedAt ?? ''),
    // 아직 정해지지 않은 기한은 맨 뒤
    ListSort.expires => (a.video?.viewExpiresAt ?? '~').compareTo(b.video?.viewExpiresAt ?? '~'),
  };

  final indexed = rows.indexed.toList()
    ..sort((a, b) {
      final c = compare(a.$2, b.$2);
      return c != 0 ? c : a.$1.compareTo(b.$1);
    });
  return [for (final e in indexed) e.$2];
}

/// 2.2 사건 목록. 언제든 돌아오는 중심 화면이다 (D-110, D-111).
/// 8번·22번은 열 때와 이름 수정·삭제 뒤에만 부른다. 주기적으로 부르지 않고 [새로고침]도 없다 (D-237).
class VideoListPage extends ConsumerStatefulWidget {
  const VideoListPage({super.key});

  @override
  ConsumerState<VideoListPage> createState() => _VideoListPageState();
}

class _VideoListPageState extends ConsumerState<VideoListPage> {
  List<VideoSummary>? _videos;
  List<VideoCase> _cases = [];
  ListSort _sort = ListSort.uploaded; // 처음은 업로드 날짜 최신순 (캔버스)
  final _search = TextEditingController();
  final _busyCases = <int>{}; // 이름 수정·삭제를 보내는 중인 사건. 다시 누르지 못하게 막는다

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final api = ref.read(apiProvider);
    try {
      final videos = await api.videos(); // 8
      var cases = <VideoCase>[];
      try {
        cases = await api.cases(); // 22. 못 읽으면 상대 이름 칸만 비운다
      } catch (_) {}
      refreshSession(ref);
      if (mounted) {
        setState(() {
          _videos = videos;
          _cases = cases;
        });
      }
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    }
  }

  List<ListRow> _rows(List<VideoSummary> videos, bool admin) {
    final byId = {for (final c in _cases) c.id: c};
    final withVideo = {for (final v in videos) v.caseId};
    final rows = [
      for (final v in videos) ListRow.video(v, byId[v.caseId]),
      // 연결만 하고 영상이 없는 사건. 관리자는 눌러 업로드 화면으로 가고, 피해자는 "업로드 중"으로 본다 (D-211, D-226)
      for (final c in _cases)
        if (!withVideo.contains(c.id)) ListRow.emptyCase(c),
    ];
    // 피해자는 수락 전 사건의 줄을 보지 않는다. 서버가 늦게 반영돼도 화면에서 거른다 (D-233)
    return admin
        ? rows
        : [
            for (final r in rows)
              if (!r.pending) r,
          ];
  }

  /// 사건 이름 수정 (27번 초안, D-237). 두 계정 모두 할 수 있다.
  Future<void> _rename(VideoCase c) async {
    final name = await showDialog<String>(
      context: context,
      builder: (_) => _RenameDialog(initial: c.name ?? ''),
    );
    if (name == null || !mounted) return;
    setState(() => _busyCases.add(c.id));
    try {
      // 백엔드 연결 필요: 27번 사건 이름 수정 (D-237 초안)
      await backendNotice(context, ref, '저장');
      await ref.read(apiProvider).renameCase(c.id, name); // 27
      if (!mounted) return;
      showMessage(context, '사건 이름을 바꿨습니다.');
      await _load();
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _busyCases.remove(c.id));
    }
  }

  /// 사건 삭제 (28번 초안, D-237). 확인창을 거친다.
  Future<void> _delete(ListRow r) async {
    final c = r.videoCase!;
    final ok = await confirm(
      context,
      '‘${r.name}’ 사건과 이 사건에 올린 영상을 더 볼 수 없습니다. 되돌릴 수 없습니다.',
      title: '사건을 삭제할까요?',
      okLabel: '삭제',
    );
    if (!ok || !mounted) return;
    setState(() => _busyCases.add(c.id));
    try {
      // 백엔드 연결 필요: 28번 사건 삭제 (D-237 초안)
      await backendNotice(context, ref, '삭제');
      await ref.read(apiProvider).deleteCase(c.id); // 28
      if (!mounted) return;
      showMessage(context, '사건을 삭제했습니다.');
      await _load();
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _busyCases.remove(c.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final videos = _videos;
    final me = ref.watch(meProvider).value;
    final admin = me?.isAdmin ?? false;
    final all = videos == null || me == null ? null : _rows(videos, admin);
    final query = _search.text.trim();
    final rows = all == null ? null : searchRows(all, query);
    // 사건이 하나도 없으면 검색칸을 두지 않는다 (캔버스 2.2 비었을 때)
    final searchBox = all == null || all.isEmpty
        ? null
        : SizedBox(
            width: isNarrow(context) ? 200 : 320,
            child: TextField(
              controller: _search,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                hintText: '사건 이름으로 검색',
                prefixIcon: Icon(Icons.search, size: 18, color: subColor),
              ),
            ),
          );
    return PageFrame(
      current: NavItem.videos,
      title: rows == null ? '사건 목록' : (query.isEmpty ? '사건 ${rows.length}건' : '검색 결과 ${rows.length}건'),
      actions: [?searchBox],
      child: rows == null
          ? const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          : all!.isEmpty
          ? StateCard(
              icon: Icons.videocam_outlined,
              title: admin ? '아직 사건이 없습니다' : '아직 올라온 영상이 없습니다',
              messages: [
                admin
                    ? '상단의 [사건 관계자 연결]에서 피해자 계정을 연결해 주세요.\n연결하면 사건이 만들어지고, 그 사건에 CCTV 영상을 올릴 수 있습니다.'
                    : '주차장 관리자에게 문의해 주세요.',
              ],
            )
          : rows.isEmpty
          ? StateCard(
              icon: Icons.search,
              title: '검색 결과가 없습니다',
              messages: ['‘$query’와 일치하는 사건 이름이 없습니다.\n이름을 다시 확인해 주세요.'],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (!_folded(context)) _HeaderRow(admin: admin, sort: _sort, onSort: (s) => setState(() => _sort = s)),
                for (final r in sortRows(rows, _sort, admin: admin)) ...[
                  _VideoRow(
                    r,
                    admin: admin,
                    onTap: _onTap(r, admin),
                    onRename: _actionsOf(r) ? () => _rename(r.videoCase!) : null,
                    onDelete: _actionsOf(r) ? () => _delete(r) : null,
                  ),
                  const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }

  /// 사건을 아는 줄만 이름 수정·삭제를 할 수 있다. 보내는 중이면 막는다.
  bool _actionsOf(ListRow r) {
    final c = r.videoCase;
    return c != null && !_busyCases.contains(c.id);
  }

  /// 누르면 갈 곳. 관리자가 올리는 중인 영상은 열 것이 없어 누를 수 없다 (캔버스).
  VoidCallback? _onTap(ListRow r, bool admin) {
    final v = r.video;
    if (v == null) return admin ? () => context.go('/cases/${r.videoCase!.id}/upload') : null;
    if (admin && v.status == VideoStatus.uploading && !v.maskedDeleted) return null;
    return () => context.go('/videos/${v.videoId}');
  }
}

/// 사건 이름 수정 창. [저장]하면 앞뒤 공백을 지운 새 이름을 돌려준다.
class _RenameDialog extends StatefulWidget {
  const _RenameDialog({required this.initial});

  final String initial;

  @override
  State<_RenameDialog> createState() => _RenameDialogState();
}

class _RenameDialogState extends State<_RenameDialog> {
  late final _name = TextEditingController(text: widget.initial);
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  void _save() {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = caseNameEmptyMessage);
      return;
    }
    Navigator.pop(context, name);
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('사건 이름 수정'),
    content: SizedBox(
      width: 392,
      child: TextField(
        controller: _name,
        autofocus: true,
        maxLength: caseNameMaxLength,
        decoration: InputDecoration(hintText: '사건 이름을 입력해 주세요', errorText: _error, counterText: ''),
        onChanged: (_) {
          if (_error != null) setState(() => _error = null);
        },
        onSubmitted: (_) => _save(),
      ),
    ),
    actions: [
      OutlinedButton(onPressed: () => Navigator.pop(context), child: const Text('취소')),
      FilledButton(onPressed: _save, child: const Text('저장')),
    ],
  );
}

class _HeaderRow extends StatelessWidget {
  const _HeaderRow({required this.admin, required this.sort, required this.onSort});

  final bool admin;
  final ListSort sort;
  final ValueChanged<ListSort> onSort;

  @override
  Widget build(BuildContext context) {
    final labels = ['사건 이름', admin ? '피해자' : '관리자', '상태', '열람기한'];
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 4),
      child: Row(
        children: [
          for (final (i, label) in labels.indexed)
            Expanded(
              flex: _columnFlex[i],
              child: Align(
                alignment: Alignment.centerLeft,
                child: _fit(
                  _SortButton(label: label, selected: sort == _headerSorts[i], onTap: () => onSort(_headerSorts[i])),
                ),
              ),
            ),
          const SizedBox(width: _deleteColumnWidth),
        ],
      ),
    );
  }
}

/// 표 머리 정렬 버튼. 고른 칸은 아래 화살표, 나머지는 위아래 화살표 (캔버스 메모).
class _SortButton extends StatelessWidget {
  const _SortButton({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    selected: selected,
    child: TextButton(
      onPressed: onTap,
      style: TextButton.styleFrom(
        foregroundColor: selected ? pointColor : noteColor,
        minimumSize: const Size(0, 32),
        padding: const EdgeInsets.symmetric(horizontal: 0),
        textStyle: const TextStyle(fontFamily: 'Pretendard', fontSize: 13, fontWeight: FontWeight.w600),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        spacing: 4,
        children: [Text(label), Icon(selected ? Icons.arrow_downward : Icons.unfold_more, size: 14)],
      ),
    ),
  );
}

/// 목록 한 줄. 카드 모양이고 누르면 상태 화면(영상 없는 사건은 업로드 화면)으로 간다.
/// 사건 이름 옆 연필로 이름을 고치고, 줄 끝 휴지통으로 사건을 지운다 (캔버스, D-237).
class _VideoRow extends StatelessWidget {
  const _VideoRow(this.row, {required this.admin, required this.onTap, this.onRename, this.onDelete});

  final ListRow row;
  final bool admin;
  final VoidCallback? onTap;
  final VoidCallback? onRename;
  final VoidCallback? onDelete;

  String get _person => (admin ? row.videoCase?.victimName : row.videoCase?.adminName) ?? '';

  Widget get _name {
    final filename = row.filename;
    return Row(
      children: [
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(row.name, style: const TextStyle(fontSize: 15)),
              if (filename != null) SmallText(filename),
            ],
          ),
        ),
        if (row.videoCase != null) EditIconButton(tooltip: '사건 이름 수정', onPressed: onRename ?? () {}),
      ],
    );
  }

  Widget get _deleteButton => SizedBox(
    width: _deleteColumnWidth,
    child: row.videoCase == null
        ? null
        : Center(
            child: DeleteIconButton(tooltip: '사건 삭제', onPressed: onDelete ?? () {}),
          ),
  );

  /// 좁은 창: 사건 이름 아래에 상대 이름·상태 칩·날짜를 접어 둔다. 표 머리가 없으므로 앞에 이름을 붙인다.
  Widget _narrow(String? expires) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: 8,
    children: [
      Row(
        children: [
          Expanded(child: _name),
          _deleteButton,
        ],
      ),
      Wrap(
        spacing: 12,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _StatusChip(row, admin: admin),
          if (_person.isNotEmpty) SmallText('${admin ? '피해자' : '관리자'} $_person'),
          SmallText(expires == null ? '열람기한: 업로드 완료 후 정해집니다' : '열람기한 ${formatKstDate(expires)}'),
        ],
      ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final expires = row.video?.viewExpiresAt;
    return Container(
      decoration: BoxDecoration(
        color: offWhiteColor,
        borderRadius: BorderRadius.circular(cardRadius),
        border: Border.all(color: lineColor),
        boxShadow: cardShadow,
      ),
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          borderRadius: BorderRadius.circular(cardRadius),
          onTap: onTap,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 56),
            child: Padding(
              padding: EdgeInsets.fromLTRB(isNarrow(context) ? 16 : 24, 6, isNarrow(context) ? 8 : 16, 6),
              child: _folded(context)
                  ? _narrow(expires)
                  : Row(
                      children: [
                        Expanded(flex: _columnFlex[0], child: _name),
                        Expanded(
                          flex: _columnFlex[1],
                          child: Text(_person, style: const TextStyle(fontSize: 15)),
                        ),
                        Expanded(
                          flex: _columnFlex[2],
                          child: Align(
                            alignment: Alignment.centerLeft,
                            child: _fit(_StatusChip(row, admin: admin)),
                          ),
                        ),
                        // 날짜만 보인다. 시각까지는 상태 화면에서 본다 (D-190)
                        Expanded(
                          flex: _columnFlex[3],
                          child: expires == null
                              ? const SmallText('업로드 완료 후 정해집니다')
                              : _fit(Text(formatKstDate(expires), style: const TextStyle(fontSize: 15))),
                        ),
                        _deleteButton,
                      ],
                    ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 상태별 색·아이콘 칩 (D-183, D-190). 색은 캔버스 색상표의 쓰임을 따르고, 크기는 캔버스 `.tag`다 (D-237).
class _StatusChip extends StatelessWidget {
  const _StatusChip(this.row, {required this.admin});

  final ListRow row;
  final bool admin;

  @override
  Widget build(BuildContext context) {
    final video = row.video;
    final pending = row.pending; // 수락 대기 중은 상태와 관계없이 기다림 색이다 (D-233)
    final group = pending
        ? StatusGroup.waiting
        : video?.listGroup(admin: admin) ?? (admin ? StatusGroup.todo : StatusGroup.waiting);
    final ended = group == StatusGroup.ended;
    final (background, foreground) = switch (group) {
      StatusGroup.todo => (pointColor, offWhiteColor),
      StatusGroup.waiting => (progressChipColor, inkColor),
      StatusGroup.done => (doneChipColor, offWhiteColor),
      StatusGroup.problem => (failChipColor, offWhiteColor),
      StatusGroup.ended => (lineColor, inkColor),
    };
    final icon = pending
        ? Icons.hourglass_empty
        : video == null
        ? (admin ? Icons.upload_outlined : Icons.hourglass_empty)
        : ended
        ? Icons.inventory_2_outlined
        : switch (video.status) {
            VideoStatus.uploading => Icons.hourglass_empty,
            VideoStatus.stillsRunning || VideoStatus.stage2Running => Icons.autorenew,
            VideoStatus.stage1Done => Icons.edit_outlined,
            VideoStatus.ready || VideoStatus.batchRunning => admin ? Icons.search : Icons.check_circle_outline,
            VideoStatus.finished || VideoStatus.exhausted => Icons.push_pin_outlined,
            VideoStatus.uploadFailed || VideoStatus.failed => Icons.priority_high,
            _ => Icons.schedule,
          };
    return Container(
      constraints: const BoxConstraints(minHeight: 36),
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(cardRadius)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: foreground),
          const SizedBox(width: 8),
          Text(
            pending
                ? '수락 대기 중'
                : video == null
                ? (admin ? '업로드 필요' : '업로드 중')
                : video.listLabel(admin: admin),
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: foreground,
              decoration: ended ? TextDecoration.lineThrough : null,
            ),
          ),
        ],
      ),
    );
  }
}
