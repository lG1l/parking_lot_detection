import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/format.dart';
import '../../core/models/analysis.dart';
import '../../core/models/video.dart';
import '../../core/widgets/clip_player.dart';
import '../../core/widgets/common.dart';
import '../candidates/completion.dart';
import '../video_status/status_rules.dart';
import '../video_status/video_status_page.dart';

/// 추정 실제 시각 줄 (D-85). 둘 중 하나라도 없으면 null.
String? estimatedTimeText(PinnedIncident p) {
  final start = p.estStartAt;
  final end = p.estEndAt;
  if (start == null || end == null) return null;
  // 같은 날이면 끝은 시각만 (07장 2.9 예: "2026-09-17 03:40:35 ~ 03:41:05")
  final sameDay = formatKstSecond(start).substring(0, 10) == formatKstSecond(end).substring(0, 10);
  final endText = sameDay ? formatKstTime(end) : formatKstSecond(end);
  return '${formatKstSecond(start)} ~ $endText (관리자 입력 기준 추정)';
}

/// 2.9 결과 (고정한 사건 지점 목록). 고정 해제·다운로드 버튼은 없다 (D-40, 불변 조건 8).
class ResultsPage extends ConsumerStatefulWidget {
  const ResultsPage({super.key, required this.videoId});

  final String videoId;

  @override
  ConsumerState<ResultsPage> createState() => _ResultsPageState();
}

class _ResultsPageState extends ConsumerState<ResultsPage> {
  int get _id => int.parse(widget.videoId);
  Api get _api => ref.read(apiProvider);

  VideoDetail? _detail;
  List<PinnedIncident>? _pins;
  DateTime? _lastUrlReload;

  @override
  void initState() {
    super.initState();
    _open();
  }

  Future<void> _open() async {
    try {
      final d = await _api.video(_id); // 9
      if (!mounted) return;
      final screen = selectScreen(d);
      if (screen != StatusScreen.results && screen != StatusScreen.exhausted) {
        goStatus(context, _id);
        return;
      }
      final pins = await _api.pins(_id); // 15
      if (!mounted) return;
      if (pins.isEmpty) {
        goStatus(context, _id); // exhausted인데 고정이 없으면 완료 화면
        return;
      }
      setState(() {
        _detail = d;
        _pins = pins;
      });
    } catch (e) {
      _onError(e);
    }
  }

  void _onError(Object e) {
    if (!mounted || handleCommonError(context, e)) return;
    final code = errorCode(e);
    if (needsStatusReload(code)) goStatus(context, _id, expired: isExpiredCode(code));
  }

  /// 재생 URL이 만료되면 15번을 다시 불러 새 URL로 이어 재생한다 (D-41).
  void _onUrlExpired() {
    final last = _lastUrlReload;
    if (last != null && DateTime.now().difference(last) < const Duration(seconds: 10)) return;
    _lastUrlReload = DateTime.now();
    _api.pins(_id).then((pins) {
      if (mounted) setState(() => _pins = pins);
    }).catchError(_onError);
  }

  @override
  Widget build(BuildContext context) {
    final d = _detail;
    final pins = _pins;
    return PageFrame(
      title: '결과',
      maxWidth: 1100,
      actions: const [BackToListButton()],
      child: d == null || pins == null
          ? const Center(child: CircularProgressIndicator())
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(resultExpiresText(d.viewExpiresAt)),
                const SizedBox(height: 12),
                if (d.status == VideoStatus.exhausted && (d.candidateUnavailable ?? 0) > 0)
                  Notice(partialUnavailableMessage(d.candidateUnavailable!)),
                for (final (i, p) in pins.indexed) _item(context, i + 1, p),
              ],
            ),
    );
  }

  Widget _item(BuildContext context, int no, PinnedIncident p) {
    final text = Theme.of(context).textTheme;
    final est = estimatedTimeText(p);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('사건 지점 $no', style: text.titleMedium),
            const SizedBox(height: 8),
            const Text('영상 시작부터'),
            // 경찰에게 바로 전달할 원본 영상 기준 시간 (07장 2.9)
            SelectableText(
              '${formatElapsed(p.startSec)} ~ ${formatElapsed(p.endSec)}',
              style: text.headlineMedium,
            ),
            if (est != null) Text(est),
            const SizedBox(height: 12),
            ClipPlayer(url: p.clipUrl, onUrlExpired: _onUrlExpired),
          ],
        ),
      ),
    );
  }
}
