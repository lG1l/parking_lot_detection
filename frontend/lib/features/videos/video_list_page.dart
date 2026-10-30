import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/format.dart';
import '../../core/models/video.dart';
import '../../core/widgets/common.dart';

/// 목록 정렬 (D-183-4). 화면에서만 정렬하고 8번을 다시 부르지 않는다.
enum _Sort { latest, needsInput }

// 표 칸 비율: 파일 이름 · 상태 · 업로드 날짜 · 열람기한 (D-190)
const _columnFlex = [21, 14, 11, 12];

/// 2.2 영상 목록. 언제든 돌아오는 중심 화면이다 (D-110, D-111).
/// 8번은 열 때와 [새로고침]에서만 부른다. 주기적으로 부르지 않는다.
class VideoListPage extends ConsumerStatefulWidget {
  const VideoListPage({super.key});

  @override
  ConsumerState<VideoListPage> createState() => _VideoListPageState();
}

class _VideoListPageState extends ConsumerState<VideoListPage> {
  List<VideoSummary>? _videos;
  bool _loading = false;
  _Sort _sort = _Sort.latest;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final videos = await ref.read(apiProvider).videos();
      if (mounted) setState(() => _videos = videos);
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  // 입력필요순 순위: 사전 입력 필요 0 → 후보 선택 가능 1 → 문제 2 → 기다림 3 → 확인 완료 4 → 종료됨 5
  int _rank(VideoSummary v) => switch (v.listGroup) {
    StatusGroup.ended => 5,
    StatusGroup.todo => v.status == VideoStatus.stage1Done ? 0 : 1,
    StatusGroup.problem => 2,
    StatusGroup.waiting => 3,
    StatusGroup.done => 4,
  };

  /// 받은 순서(최신순)를 기본으로 하고, 입력필요순은 순위가 같으면 받은 순서를 지킨다.
  /// Dart의 List.sort는 안정 정렬이 아니라서 원래 위치를 함께 비교한다.
  List<VideoSummary> _sorted(List<VideoSummary> videos) {
    if (_sort == _Sort.latest) return videos;
    final indexed = videos.indexed.toList()
      ..sort((a, b) {
        final byRank = _rank(a.$2).compareTo(_rank(b.$2));
        return byRank != 0 ? byRank : a.$1.compareTo(b.$1);
      });
    return [for (final e in indexed) e.$2];
  }

  @override
  Widget build(BuildContext context) {
    final videos = _videos;
    return PageFrame(
      current: NavItem.videos,
      title: '내 영상',
      actions: [
        if (videos != null && videos.isNotEmpty)
          DropdownButton<_Sort>(
            value: _sort,
            underline: const SizedBox.shrink(),
            items: const [
              DropdownMenuItem(value: _Sort.latest, child: Text('최신순')),
              DropdownMenuItem(value: _Sort.needsInput, child: Text('입력필요순')),
            ],
            onChanged: (v) => setState(() => _sort = v ?? _sort),
          ),
        OutlinedButton(onPressed: _loading ? null : _load, child: const Text('새로고침')),
      ],
      child: videos == null
          ? const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          : videos.isEmpty
          ? StateCard(
              icon: Icons.videocam_outlined,
              title: '아직 올라온 영상이 없습니다',
              messages: const ['업로드 링크를 발급해 주차장 관리자에게 전달하면,\n관리자가 올린 CCTV 영상이 이곳에 나타납니다.'],
              actions: [
                FilledButton(
                  style: largeButtonStyle,
                  onPressed: () => context.go('/videos/upload-link'),
                  child: const Text('업로드 링크 발급'),
                ),
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (!isNarrow(context)) const _HeaderRow(),
                for (final v in _sorted(videos)) ...[
                  _VideoRow(v, onTap: () => context.go('/videos/${v.videoId}')),
                  const SizedBox(height: 8),
                ],
              ],
            ),
    );
  }
}

class _HeaderRow extends StatelessWidget {
  const _HeaderRow();

  @override
  Widget build(BuildContext context) {
    const style = TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: noteColor);
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 0, 24, 8),
      child: Row(
        children: [
          for (final (i, label) in ['파일 이름', '상태', '업로드 날짜', '열람기한'].indexed)
            Expanded(
              flex: _columnFlex[i],
              child: Text(label, style: style),
            ),
        ],
      ),
    );
  }
}

/// 영상 한 줄. 카드 모양이고 누르면 상태 화면으로 간다.
class _VideoRow extends StatelessWidget {
  const _VideoRow(this.video, {required this.onTap});

  final VideoSummary video;
  final VoidCallback onTap;

  /// 좁은 창: 파일 이름 아래에 상태 칩과 날짜를 접어 둔다. 표 머리가 없으므로 날짜 앞에 이름을 붙인다.
  Widget _narrow(String? created, String? expires) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: 8,
    children: [
      Text(video.originalFilename, style: const TextStyle(fontSize: 15)),
      Wrap(
        spacing: 12,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _StatusChip(video),
          if (created != null) SmallText('업로드 ${formatKstDate(created)}'),
          SmallText(expires == null ? '열람기한: 업로드 완료 후 정해집니다' : '열람기한 ${formatKstDate(expires)}'),
        ],
      ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final expires = video.viewExpiresAt;
    final created = video.createdAt;
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
              child: isNarrow(context)
                  ? _narrow(created, expires)
                  : Row(
                      children: [
                        Expanded(
                          flex: _columnFlex[0],
                          child: Text(video.originalFilename, style: const TextStyle(fontSize: 15)),
                        ),
                        Expanded(
                          flex: _columnFlex[1],
                          child: Align(alignment: Alignment.centerLeft, child: _StatusChip(video)),
                        ),
                        Expanded(
                          flex: _columnFlex[2],
                          child: Text(
                            created == null ? '' : formatKstDate(created),
                            style: const TextStyle(fontSize: 15),
                          ),
                        ),
                        // 날짜만 보인다. 시각까지는 상태 화면에서 본다 (D-190)
                        Expanded(
                          flex: _columnFlex[3],
                          child: expires == null
                              ? const SmallText('업로드 완료 후 정해집니다')
                              : Text(formatKstDate(expires), style: const TextStyle(fontSize: 15)),
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
  const _StatusChip(this.video);

  final VideoSummary video;

  @override
  Widget build(BuildContext context) {
    final ended = video.listGroup == StatusGroup.ended;
    final (background, foreground) = switch (video.listGroup) {
      StatusGroup.todo => (pointColor, offWhiteColor),
      StatusGroup.waiting => (progressChipColor, inkColor),
      StatusGroup.done => (doneChipColor, offWhiteColor),
      StatusGroup.problem => (failChipColor, offWhiteColor),
      StatusGroup.ended => (lineColor, inkColor),
    };
    final icon = ended
        ? Icons.inventory_2_outlined
        : switch (video.status) {
            VideoStatus.uploading => Icons.hourglass_empty,
            VideoStatus.stillsRunning || VideoStatus.stage2Running => Icons.autorenew,
            VideoStatus.stage1Done => Icons.edit_outlined,
            VideoStatus.ready || VideoStatus.batchRunning => Icons.search,
            VideoStatus.finished || VideoStatus.exhausted => Icons.check_circle_outline,
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
            video.listLabel,
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
