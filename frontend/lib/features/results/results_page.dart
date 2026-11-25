import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/format.dart';
import '../../core/models/analysis.dart';
import '../../core/models/video.dart';
import '../../core/session.dart';
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
/// 피해자 계정은 클립 없이 고정한 시각만 본다 (D-211).
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
  bool _admin = false;
  DateTime? _lastUrlReload;

  @override
  void initState() {
    super.initState();
    _open();
  }

  Future<void> _open() async {
    try {
      final me = await ref.read(meProvider.future);
      final d = await _api.video(_id); // 9
      if (!mounted) return;
      final screen = selectScreen(d, admin: me.isAdmin);
      if (screen != StatusScreen.results && screen != StatusScreen.exhausted) {
        goStatus(context, _id);
        return;
      }
      // 피해자 계정은 재생 URL 없는 사건 지점 시간만 받는다 (D-210)
      final pins = me.isAdmin ? await _api.pins(_id) : await _api.incidentTimes(_id); // 15 / 25
      if (!mounted) return;
      if (pins.isEmpty) {
        goStatus(context, _id); // exhausted인데 고정이 없으면 완료 화면
        return;
      }
      setState(() {
        _admin = me.isAdmin;
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
    _api
        .pins(_id)
        .then((pins) {
          if (mounted) setState(() => _pins = pins);
        })
        .catchError(_onError);
  }

  @override
  Widget build(BuildContext context) {
    final d = _detail;
    final pins = _pins;
    return PageFrame(
      // 불러오는 동안은 제목·소제목을 비워 둔다. 임시 제목 "결과"가 보였다가 바뀌지 않게 한다
      eyebrow: d == null ? null : '고정 목록',
      eyebrowNotes: d == null ? const [] : [...counterpartNote(ref, _id), viewExpiresText(d.viewExpiresAt)],
      title: d?.originalFilename,
      titleStrong: withoutExtension(d?.originalFilename),
      child: d == null || pins == null
          ? const Center(child: CircularProgressIndicator())
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (!_admin) ...[
                  const SmallText('고정된 장면의 시각만 볼 수 있습니다. 장면 영상은 관리자 화면에서 관리자와 함께 확인합니다.'),
                  const SizedBox(height: 16),
                ],
                if (d.status == VideoStatus.exhausted && (d.candidateUnavailable ?? 0) > 0) ...[
                  Notice(partialUnavailableMessage(d.candidateUnavailable!)),
                  const SizedBox(height: 16),
                ],
                _grid(pins),
              ],
            ),
    );
  }

  /// 넓으면 영상 상자 2열, 좁으면 1열 (캔버스 2.9). 피해자 계정은 영상 없이 시각만이라 1열 줄이다.
  Widget _grid(List<PinnedIncident> pins) {
    const gap = 28.0;
    return LayoutBuilder(
      builder: (context, c) {
        final columns = _admin && c.maxWidth >= 720 ? 2 : 1;
        final width = (c.maxWidth - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: 24,
          children: [for (final p in pins) SizedBox(width: width, child: _item(p))],
        );
      },
    );
  }

  /// 윗선 아래 "영상 시작부터" + 영상 + 원본 기준 시간 굵게 + 추정 실제 시각 작게 (캔버스 2.9, D-305).
  Widget _item(PinnedIncident p) {
    final est = estimatedTimeText(p);
    final clipUrl = p.clipUrl;
    // 피해자 계정은 클립 주소를 받지 않는다. 시각만 보인다 (D-211)
    final showClip = _admin && clipUrl != null;
    return Container(
      padding: const EdgeInsets.only(top: 16),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: lineColor))),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('영상 시작부터', style: kickerStyle),
          const SizedBox(height: 14),
          if (showClip) ...[
            ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: ClipPlayer(url: clipUrl, onUrlExpired: _onUrlExpired),
            ),
            const SizedBox(height: 14),
          ],
          // 경찰에게 바로 전달할 원본 영상 기준 시간 (07장 2.9)
          SelectableText(
            '${formatElapsed(p.startSec)} ~ ${formatElapsed(p.endSec)}',
            style: TextStyle(
              fontSize: showClip ? 22 : 40,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.5,
              color: inkColor,
            ),
          ),
          if (est != null) ...[const SizedBox(height: 10), SmallText(est)],
        ],
      ),
    );
  }
}
