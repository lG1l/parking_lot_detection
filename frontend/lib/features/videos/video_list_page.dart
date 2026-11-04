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

/// 표 머리를 눌러 고르는 정렬 (D-211). 화면에서만 정렬하고 8번을 다시 부르지 않는다.
enum ListSort { name, person, status, uploaded, expires }

// 표 칸 비율: 파일 이름 · 피해자(관리자) · 상태 · 업로드 날짜 · 열람기한 (캔버스 2.2)
const _columnFlex = [28, 14, 15, 10, 12];

/// 다섯 칸 표를 펼칠 최소 창 폭. 이보다 좁으면 칸이 모자라 날짜가 줄바꿈되고 칩이 넘치므로,
/// 좁은 창처럼 파일 이름 아래에 접어 보인다.
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

  String get name => video?.originalFilename ?? '';

  /// 업로드 날짜. 영상 없는 사건은 연결한 날로 정렬한다.
  String? get uploadedAt => video?.createdAt ?? videoCase?.createdAt;
}

/// 정렬. 파일 이름·상대 이름은 가나다순, 상태는 할 일이 먼저, 업로드 날짜는 최신순, 열람기한은 가까운 순이다.
/// 같으면 받은 순서(최신순)를 지킨다. Dart의 List.sort는 안정 정렬이 아니라서 원래 위치를 함께 비교한다.
List<ListRow> sortRows(List<ListRow> rows, ListSort sort, {required bool admin}) {
  // 상태 순위: 업로드 필요·사전 입력 필요 0 → 후보 선택 가능 1 → 문제 2 → 기다림 3 → 완료 4 → 종료됨 5
  int rank(ListRow r) {
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

/// 2.2 사건·영상 목록. 언제든 돌아오는 중심 화면이다 (D-110, D-111).
/// 8번·22번은 열 때와 [새로고침]에서만 부른다. 주기적으로 부르지 않는다.
class VideoListPage extends ConsumerStatefulWidget {
  const VideoListPage({super.key});

  @override
  ConsumerState<VideoListPage> createState() => _VideoListPageState();
}

class _VideoListPageState extends ConsumerState<VideoListPage> {
  List<VideoSummary>? _videos;
  List<VideoCase> _cases = [];
  bool _loading = false;
  ListSort _sort = ListSort.uploaded; // 처음은 업로드 날짜 최신순 (캔버스)

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
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
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<ListRow> _rows(List<VideoSummary> videos, bool admin) {
    final byId = {for (final c in _cases) c.id: c};
    final withVideo = {for (final v in videos) v.caseId};
    return [
      for (final v in videos) ListRow.video(v, byId[v.caseId]),
      // 연결만 하고 영상이 없는 사건. 관리자는 눌러 업로드 화면으로 가고, 피해자는 "업로드 중"으로 본다 (D-211, D-226)
      for (final c in _cases)
        if (!withVideo.contains(c.id)) ListRow.emptyCase(c),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final videos = _videos;
    final me = ref.watch(meProvider).value;
    final admin = me?.isAdmin ?? false;
    final rows = videos == null || me == null ? null : _rows(videos, admin);
    return PageFrame(
      current: NavItem.videos,
      title: rows == null ? '영상 목록' : (admin ? '사건 ${rows.length}건' : '영상 ${rows.length}건'),
      actions: [OutlinedButton(onPressed: _loading ? null : _load, child: const Text('새로고침'))],
      child: rows == null
          ? const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          : rows.isEmpty
          ? StateCard(
              icon: Icons.videocam_outlined,
              title: admin ? '아직 사건이 없습니다' : '아직 올라온 영상이 없습니다',
              messages: [
                admin
                    ? '상단의 [사건 관계자 연결]에서 피해자 계정을 연결해 주세요.\n연결하면 사건이 만들어지고, 그 사건에 CCTV 영상을 올릴 수 있습니다.'
                    : '주차장 관리자에게 문의해 주세요.',
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (!admin) ...[
                  const SmallText('영상은 주차장 관리자가 올립니다. 분석이 끝난 결과는 관리자 화면에서 관리자와 함께 확인합니다.'),
                  const SizedBox(height: 16),
                ],
                if (!_folded(context)) _HeaderRow(admin: admin, sort: _sort, onSort: (s) => setState(() => _sort = s)),
                for (final r in sortRows(rows, _sort, admin: admin)) ...[
                  _VideoRow(r, admin: admin, onTap: _onTap(r, admin)),
                  const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }

  /// 누르면 갈 곳. 관리자가 올리는 중인 영상은 열 것이 없어 누를 수 없다 (캔버스).
  VoidCallback? _onTap(ListRow r, bool admin) {
    final v = r.video;
    if (v == null) return admin ? () => context.go('/cases/${r.videoCase!.id}/upload') : null;
    if (admin && v.status == VideoStatus.uploading && !v.maskedDeleted) return null;
    return () => context.go('/videos/${v.videoId}');
  }
}

class _HeaderRow extends StatelessWidget {
  const _HeaderRow({required this.admin, required this.sort, required this.onSort});

  final bool admin;
  final ListSort sort;
  final ValueChanged<ListSort> onSort;

  @override
  Widget build(BuildContext context) {
    final labels = ['파일 이름', admin ? '피해자' : '관리자', '상태', '업로드 날짜', '열람기한'];
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
                  _SortButton(
                    label: label,
                    selected: sort == ListSort.values[i],
                    onTap: () => onSort(ListSort.values[i]),
                  ),
                ),
              ),
            ),
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
class _VideoRow extends StatelessWidget {
  const _VideoRow(this.row, {required this.admin, required this.onTap});

  final ListRow row;
  final bool admin;
  final VoidCallback? onTap;

  String get _person => (admin ? row.videoCase?.victimName : row.videoCase?.adminName) ?? '';

  Widget get _name => row.video == null
      ? const Text('아직 올린 영상이 없습니다', style: TextStyle(fontSize: 15, color: noteColor))
      : Text(row.name, style: const TextStyle(fontSize: 15));

  /// 좁은 창: 파일 이름 아래에 상대 이름·상태 칩·날짜를 접어 둔다. 표 머리가 없으므로 앞에 이름을 붙인다.
  Widget _narrow(String? created, String? expires) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: 8,
    children: [
      _name,
      Wrap(
        spacing: 12,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _StatusChip(row, admin: admin),
          if (_person.isNotEmpty) SmallText('${admin ? '피해자' : '관리자'} $_person'),
          if (created != null && row.video != null) SmallText('업로드 ${formatKstDate(created)}'),
          SmallText(expires == null ? '열람기한: 업로드 완료 후 정해집니다' : '열람기한 ${formatKstDate(expires)}'),
        ],
      ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final expires = row.video?.viewExpiresAt;
    final created = row.video?.createdAt;
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
              padding: EdgeInsets.symmetric(horizontal: isNarrow(context) ? 16 : 24, vertical: 8),
              child: _folded(context)
                  ? _narrow(created, expires)
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
                        Expanded(
                          flex: _columnFlex[3],
                          child: _fit(
                            Text(created == null ? '' : formatKstDate(created), style: const TextStyle(fontSize: 15)),
                          ),
                        ),
                        // 날짜만 보인다. 시각까지는 상태 화면에서 본다 (D-190)
                        Expanded(
                          flex: _columnFlex[4],
                          child: expires == null
                              ? const SmallText('업로드 완료 후 정해집니다')
                              : _fit(Text(formatKstDate(expires), style: const TextStyle(fontSize: 15))),
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

/// 상태별 색·아이콘 칩 (D-183, D-190). 색은 캔버스 색상표의 쓰임을 따른다.
class _StatusChip extends StatelessWidget {
  const _StatusChip(this.row, {required this.admin});

  final ListRow row;
  final bool admin;

  @override
  Widget build(BuildContext context) {
    final video = row.video;
    final group = video?.listGroup(admin: admin) ?? (admin ? StatusGroup.todo : StatusGroup.waiting);
    final ended = group == StatusGroup.ended;
    final (background, foreground) = switch (group) {
      StatusGroup.todo => (pointColor, offWhiteColor),
      StatusGroup.waiting => (progressChipColor, inkColor),
      StatusGroup.done => (doneChipColor, offWhiteColor),
      StatusGroup.problem => (failChipColor, offWhiteColor),
      StatusGroup.ended => (lineColor, inkColor),
    };
    final icon = video == null
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
      constraints: const BoxConstraints(minHeight: 32),
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(color: background, borderRadius: BorderRadius.circular(cardRadius)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 15, color: foreground),
          const SizedBox(width: 6),
          Text(
            video == null ? (admin ? '업로드 필요' : '업로드 중') : video.listLabel(admin: admin),
            style: TextStyle(
              fontSize: 13,
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
