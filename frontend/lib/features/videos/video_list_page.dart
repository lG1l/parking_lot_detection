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
          Row(
            children: [
              // 확인이 끝나지 않은 영상이 있어도 늘 누를 수 있다 (D-110)
              FilledButton.icon(
                onPressed: () => context.go('/videos/upload-link'),
                icon: const Icon(Icons.link),
                label: const Text('업로드 링크 받기'),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (!useBackend) ...[
            const Notice(
              '데모 화면입니다. 백엔드 없이 예시 데이터로 보여줍니다. 영상마다 상태가 달라 눌러 보면 각 화면을 볼 수 있습니다.',
              icon: Icons.science_outlined,
            ),
            const SizedBox(height: 8),
          ],
          const Notice('확인을 끝내지 않은 영상도 목록에서 다시 열어 이어서 볼 수 있습니다. 영상마다 열람기한이 다릅니다.'),
          const SizedBox(height: 8),
          if (videos == null)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (videos.isEmpty)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: Text('아직 올라온 영상이 없습니다. 업로드 링크를 받아 주차장 관리자에게 전달해 주세요.')),
            )
          else
            for (final v in videos)
              Card(
                child: ListTile(
                  title: Text(v.originalFilename),
                  subtitle: Text(viewExpiresText(v.viewExpiresAt)),
                  trailing: Chip(label: Text(statusLabel(v.status))),
                  onTap: () => context.go('/videos/${v.videoId}'),
                ),
              ),
        ],
      ),
    );
  }
}
