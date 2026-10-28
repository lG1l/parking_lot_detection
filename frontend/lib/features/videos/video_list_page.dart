import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/config.dart';
import '../../core/format.dart';
import '../../core/models/video.dart';
import '../../core/widgets/common.dart';

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

  Future<void> _logout() async {
    // 백엔드 연결 필요: 2번 로그아웃
    await backendNotice(context, ref, '로그아웃');
    try {
      await ref.read(apiProvider).logout();
    } on ApiException {
      // 로그아웃은 실패해도 로그인 화면으로 간다
    }
    if (mounted) context.go('/login');
  }

  // 확인이 끝나지 않은 영상이 있어도 늘 누를 수 있다 (D-110)
  Widget _uploadLinkButton(BuildContext context) => FilledButton.icon(
    onPressed: () => context.go('/videos/upload-link'),
    icon: const Icon(Icons.link),
    label: const Text('업로드 링크 받기'),
  );

  @override
  Widget build(BuildContext context) {
    final videos = _videos;
    return PageFrame(
      title: '내 영상',
      actions: [
        IconButton(
          tooltip: '새로고침',
          onPressed: _loading ? null : _load,
          icon: const Icon(Icons.refresh),
        ),
        TextButton(onPressed: _logout, child: const Text('로그아웃')),
      ],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (!useBackend) ...[
            const Notice(
              '데모 화면입니다. 백엔드 없이 예시 데이터로 보여줍니다. 영상마다 상태가 달라 눌러 보면 각 화면을 볼 수 있습니다.',
              icon: Icons.science_outlined,
            ),
            const SizedBox(height: 16),
          ],
          Row(
            children: [
              Text(videos == null ? '영상' : '영상 ${videos.length}건', style: Theme.of(context).textTheme.titleMedium),
              const Spacer(),
              _uploadLinkButton(context),
            ],
          ),
          const SizedBox(height: 12),
          // 정렬 드롭다운은 이 줄 오른쪽에 들어간다 (D-182-3)
          Row(
            children: [
              Icon(Icons.info_outline, size: 18, color: Theme.of(context).colorScheme.outline),
              const SizedBox(width: 8),
              const Expanded(
                child: Text('확인을 끝내지 않은 영상도 목록에서 다시 열어 이어서 볼 수 있습니다. 영상마다 열람기한이 다릅니다.'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (videos == null)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (videos.isEmpty)
            Padding(
              padding: const EdgeInsets.all(32),
              child: Column(
                children: [
                  Icon(Icons.movie_outlined, size: 48, color: Theme.of(context).colorScheme.outline),
                  const SizedBox(height: 12),
                  const Text('아직 올라온 영상이 없습니다. 업로드 링크를 받아 주차장 관리자에게 전달해 주세요.', textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  _uploadLinkButton(context),
                ],
              ),
            )
          else
            for (final v in videos)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.movie_outlined),
                  title: Text(v.originalFilename),
                  subtitle: Text(viewExpiresText(v.viewExpiresAt)),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _StatusChip(v.status),
                      const Icon(Icons.chevron_right),
                    ],
                  ),
                  onTap: () => context.go('/videos/${v.videoId}'),
                ),
              ),
        ],
      ),
    );
  }
}

/// 상태 묶음별 색·아이콘 칩 (D-182). 색은 테마 이름으로만 쓴다.
class _StatusChip extends StatelessWidget {
  const _StatusChip(this.status);

  final String status;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (background, foreground, icon) = switch (statusGroup(status)) {
      StatusGroup.todo => (scheme.primary, scheme.onPrimary, Icons.touch_app_outlined),
      StatusGroup.waiting => (scheme.secondaryContainer, scheme.onSecondaryContainer, Icons.hourglass_empty),
      StatusGroup.done => (scheme.inverseSurface, scheme.onInverseSurface, Icons.check),
      StatusGroup.problem => (scheme.errorContainer, scheme.onErrorContainer, Icons.priority_high),
    };
    return Chip(
      avatar: Icon(icon, size: 18, color: foreground),
      label: Text(statusLabel(status)),
      labelStyle: TextStyle(color: foreground),
      backgroundColor: background,
      side: BorderSide.none,
    );
  }
}
