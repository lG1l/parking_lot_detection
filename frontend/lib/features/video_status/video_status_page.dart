import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/constants.dart';
import '../../core/format.dart';
import '../../core/models/video.dart';
import '../../core/widgets/common.dart';
import '../candidates/completion.dart';
import '../results/expired_view.dart';
import 'status_rules.dart';

/// 따로 주소가 있는 화면의 경로. 대기·실패·완료·보관 종료는 이 화면 안에서 그린다.
String? screenPath(int videoId, StatusScreen screen) => switch (screen) {
  StatusScreen.input => '/videos/$videoId/input',
  StatusScreen.candidates => '/videos/$videoId/candidates',
  StatusScreen.results => '/videos/$videoId/results',
  _ => null,
};

/// 상태 화면으로 돌아가 9번부터 다시 그린다 (07장 3.1).
/// [expired]: 서버가 MASKED_EXPIRED·RAW_EXPIRED로 답했다. 열람기한이 지났어도 파기 작업이 돌기
/// 전에는 9번의 masked_deleted가 false라, 이 표시 없이 9번만 보면 같은 화면을 오가게 된다.
void goStatus(BuildContext context, int videoId, {bool expired = false}) =>
    redirectTo(context, expired ? '/videos/$videoId?expired=1' : '/videos/$videoId');

bool isExpiredCode(String code) => code == 'MASKED_EXPIRED' || code == 'RAW_EXPIRED';

/// 2.5 영상 상태. 목록에서 영상을 누르면 늘 여기부터 온다 (07장 3.7).
/// 9번을 5초마다 불러 화면을 고른다 (D-138).
class VideoStatusPage extends ConsumerStatefulWidget {
  const VideoStatusPage({super.key, required this.videoId, this.expired = false});

  final String videoId;
  final bool expired;

  @override
  ConsumerState<VideoStatusPage> createState() => _VideoStatusPageState();
}

class _VideoStatusPageState extends ConsumerState<VideoStatusPage> {
  VideoDetail? _detail;
  StatusScreen? _screen;
  Timer? _timer;
  bool _retrying = false;
  late bool _serverExpired = widget.expired;

  int get _id => int.parse(widget.videoId);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _timer?.cancel(); // 화면을 떠나면 조회를 멈춘다. 분석은 계속된다 (D-111)
    super.dispose();
  }

  Future<void> _load() async {
    _timer?.cancel();
    final api = ref.read(apiProvider);
    try {
      final d = await api.video(_id); // 9
      if (!mounted) return;
      var screen = _serverExpired ? StatusScreen.expired : selectScreen(d);
      if (screen == StatusScreen.exhausted && (d.candidateTotal ?? 0) > 0) {
        // 고정한 것이 있으면 결과 화면 (07장 2.8)
        final pins = await api.pins(_id); // 15
        if (!mounted) return;
        if (pins.isNotEmpty) screen = StatusScreen.results;
      }
      final path = screenPath(_id, screen);
      if (path != null) {
        redirectTo(context, path);
        return;
      }
      setState(() {
        _detail = d;
        _screen = screen;
      });
      if (screen != StatusScreen.expired && shouldPoll(d)) _timer = Timer(pollInterval, _load);
    } catch (e) {
      if (!mounted) return;
      if (isExpiredCode(errorCode(e))) {
        showMessage(context, errorMessage(errorCode(e)));
        _serverExpired = true;
        await _load();
        return;
      }
      if (!handleCommonError(context, e)) _timer = Timer(pollInterval, _load);
    }
  }

  Future<void> _retry() async {
    setState(() => _retrying = true); // 누르는 즉시 막는다
    // 백엔드 연결 필요: 19번 분석 다시 시도
    await backendNotice(context, ref, '분석 다시 시도');
    try {
      await ref.read(apiProvider).retry(_id); // 19
      if (!mounted) return;
      setState(() => _retrying = false);
      await _load(); // 접수되면 주기 조회를 다시 시작한다
    } catch (e) {
      if (!mounted) return;
      setState(() => _retrying = false);
      if (handleCommonError(context, e)) return;
      if (isExpiredCode(errorCode(e))) _serverExpired = true;
      if (needsStatusReload(errorCode(e))) await _load();
      // 500이면 아무것도 바뀌지 않았으므로 버튼만 다시 풀린다
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _detail;
    return PageFrame(
      eyebrow: switch (_screen) {
        StatusScreen.expired => '보관 기간 종료',
        StatusScreen.exhausted => '후보 확인',
        _ => null,
      },
      eyebrowNote: _screen == StatusScreen.exhausted && d != null ? resultExpiresText(d.viewExpiresAt) : null,
      title: d?.originalFilename ?? '영상 상태',
      child: d == null ? const Center(child: CircularProgressIndicator()) : _body(context, d),
    );
  }

  Widget _body(BuildContext context, VideoDetail d) {
    final ending = const {VideoStatus.finished, VideoStatus.exhausted, VideoStatus.failed}.contains(d.status);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        switch (_screen!) {
          StatusScreen.expired => const ExpiredView(),
          StatusScreen.exhausted => _completion(context, d),
          StatusScreen.failed => _failure(context, d),
          _ => _waiting(d),
        },
        const SizedBox(height: 16),
        if (d.durationSec != null) SmallText('영상 길이 ${formatElapsed(d.durationSec!)}'),
        if (!ending && !d.maskedDeleted) SmallText(viewExpiresText(d.viewExpiresAt)),
      ],
    );
  }

  /// 대기·분석 중: 진행 표시 아래 첫 문구를 크게, 나머지를 보통 크기로 (D-190).
  Widget _waiting(VideoDetail d) {
    final messages = waitingMessages(d);
    return PageCard(
      padding: const EdgeInsets.all(32),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 380),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const BigSpinner(),
            const SizedBox(height: 16),
            Text(
              messages.first,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600, height: 1.5),
            ),
            for (final m in messages.skip(1)) ...[
              const SizedBox(height: 16),
              Text(m, textAlign: TextAlign.center, style: const TextStyle(fontSize: 15, height: 1.6)),
            ],
          ],
        ),
      ),
    );
  }

  /// 2.8 완료. 고정한 것이 없을 때만 여기서 그린다 (있으면 결과 화면).
  Widget _completion(BuildContext context, VideoDetail d) {
    final none = (d.candidateTotal ?? 0) == 0;
    return StateCard(
      icon: none ? Icons.search : Icons.check_circle_outline,
      title: completionMessage(d),
      messages: [if (none) '이 영상에서는 확인할 후보 구간을 찾지 못했습니다.'],
      // 버튼 없이 안내만 둔다. 목록으로는 상단 메뉴로 간다 (D-190)
    );
  }

  Widget _failure(BuildContext context, VideoDetail d) {
    final notice = failureNotice(d);
    return StateCard(
      icon: Icons.error_outline,
      iconColor: failColor,
      messages: [
        notice.message,
        if (notice.action == FailureAction.retry) _retrying ? '다시 시도를 요청하는 중입니다.' : '다시 시도 가능: ${d.retryLeft ?? 0}회 남음',
      ],
      actions: [
        if (notice.action == FailureAction.retry)
          FilledButton(style: largeButtonStyle, onPressed: _retrying ? null : _retry, child: const Text('분석 다시 시도')),
        if (notice.action == FailureAction.uploadLink)
          FilledButton(
            style: largeButtonStyle,
            onPressed: () => context.go('/videos/upload-link'),
            child: const Text('업로드 링크 받기'),
          ),
      ],
    );
  }
}
