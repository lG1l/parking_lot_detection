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
import '../../core/session.dart';
import '../../core/widgets/common.dart';
import '../candidates/completion.dart';
import '../results/expired_view.dart';
import 'status_rules.dart';
import 'supervision_dialog.dart';

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
/// [agreed]: 후보 확인 화면에서 끝내고 오는 길이라 안내창을 다시 띄우지 않는다 (D-226).
/// 동의가 30분을 넘겼으면 서버가 403으로 막고, 그때는 안내창을 다시 띄운다.
void goStatus(BuildContext context, int videoId, {bool expired = false, bool agreed = false}) {
  final query = [if (expired) 'expired=1', if (agreed) 'agreed=1'].join('&');
  redirectTo(context, query.isEmpty ? '/videos/$videoId' : '/videos/$videoId?$query');
}

bool isExpiredCode(String code) => code == 'MASKED_EXPIRED' || code == 'RAW_EXPIRED';

/// 화면 머리의 상대 계정 ("피해자 ○○" / "관리자 ○○"). 아직 모르면 빈 목록.
List<String> counterpartNote(WidgetRef ref, int videoId) {
  final me = ref.watch(meProvider).value;
  final c = ref.watch(caseOfVideoProvider).value?[videoId];
  if (me == null || c == null) return const [];
  return [c.counterpart(admin: me.isAdmin)];
}

/// 2.5 영상 상태. 목록에서 영상을 누르면 늘 여기부터 온다 (07장 3.7).
/// 9번을 5초마다 불러 화면을 고른다 (D-138). 갈 화면은 계정 역할에 따라 다르다 (D-204).
class VideoStatusPage extends ConsumerStatefulWidget {
  const VideoStatusPage({super.key, required this.videoId, this.expired = false, this.agreed = false});

  final String videoId;
  final bool expired;
  final bool agreed;

  @override
  ConsumerState<VideoStatusPage> createState() => _VideoStatusPageState();
}

class _VideoStatusPageState extends ConsumerState<VideoStatusPage> {
  VideoDetail? _detail;
  StatusScreen? _screen;
  bool _admin = false;
  Timer? _timer;
  bool _retrying = false;
  late bool _serverExpired = widget.expired;

  /// 이 화면에서 관리·감독 안내에 동의했는지. 동의하면 23번이 기록하고 다음 화면을 연다.
  late bool _agreed = widget.agreed;

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
      final me = await ref.read(meProvider.future); // 3 (처음 한 번)
      final d = await api.video(_id); // 9
      if (!mounted) return;
      final admin = me.isAdmin;
      var screen = _serverExpired ? StatusScreen.expired : selectScreen(d, admin: admin);

      // 관리자 계정은 후보·완료·결과 화면에 들어갈 때마다 안내창에 동의한다 (D-204)
      if (admin && needsSupervision(screen) && !_agreed) {
        setState(() {
          _admin = admin;
          _detail = d;
          _screen = null;
        });
        if (!await askSupervision(context) || !mounted) {
          if (mounted) context.go('/videos');
          return;
        }
        // 백엔드 연결 필요: 23번 관리·감독 안내 동의
        await backendNotice(context, ref, '동의하고 열람');
        await api.agreeViewing(_id); // 23
        _agreed = true;
        if (!mounted) return;
      }

      if (!admin && (screen == StatusScreen.results || screen == StatusScreen.exhausted)) {
        // 피해자: 사건 지점 시간이 있으면 결과 화면, 없으면 분석 완료 안내 (D-210)
        final times = await api.incidentTimes(_id); // 25
        if (!mounted) return;
        screen = times.isNotEmpty ? StatusScreen.results : StatusScreen.analysisDone;
      } else if (screen == StatusScreen.exhausted && (d.candidateTotal ?? 0) > 0) {
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
        _admin = admin;
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
      if (errorCode(e) == 'SUPERVISION_AGREEMENT_REQUIRED') {
        _agreed = false; // 안내창을 다시 띄운다
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
    final screen = _screen;
    // 목록으로는 두 계정 모두 상단 메뉴 [사건 목록]으로 간다 (D-190, D-211)
    // 모든 화면의 제목 위: "서브제목 | 피해자(관리자) ○○ | 열람기한" (D-211)
    return PageFrame(
      eyebrow: switch (screen) {
        null => null,
        StatusScreen.expired => '보관 기간 종료',
        StatusScreen.exhausted => '후보 확인',
        _ => '영상 상태',
      },
      eyebrowNotes: switch (screen) {
        _ when d == null || screen == null => const [],
        StatusScreen.expired => [
          ...counterpartNote(ref, _id),
          if (d.viewExpiresAt != null) '${formatKstDate(d.viewExpiresAt!)} 열람 기한 종료',
        ],
        // 열람기한은 업로드가 끝나 정해진 뒤에만 보인다 (D-211)
        _ => [...counterpartNote(ref, _id), if (d.viewExpiresAt != null) viewExpiresText(d.viewExpiresAt)],
      },
      title: d?.originalFilename ?? '영상 상태',
      child: d == null || screen == null ? const Center(child: CircularProgressIndicator()) : _body(context, d, screen),
    );
  }

  Widget _body(BuildContext context, VideoDetail d, StatusScreen screen) {
    final step = progressStep(d);
    final withSteps = (screen == StatusScreen.waiting || screen == StatusScreen.analysisDone) && step != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (withSteps) ...[_ProgressSteps(current: step), const SizedBox(height: 16)],
        switch (screen) {
          StatusScreen.expired => const ExpiredView(),
          StatusScreen.exhausted => _completion(context, d),
          StatusScreen.failed => _failure(context, d),
          StatusScreen.analysisDone => _waiting(analysisDoneMessages, icon: Icons.check_circle_outline),
          _ => _waiting(
            waitingMessages(d, admin: _admin),
            icon: switch (d.status) {
              VideoStatus.stage1Done when !d.inputDone => Icons.edit_note, // 관리자: 피해자 입력 기다림
              VideoStatus.uploadFailed => Icons.help_outline,
              _ => null,
            },
            action: _admin && d.status == VideoStatus.uploadFailed ? _uploadButton() : null,
          ),
        },
        const SizedBox(height: 16),
        // 열람기한은 제목 위 작은 글자로 옮겼다 (D-211)
        if (screen != StatusScreen.expired && d.durationSec != null) SmallText('영상 길이 ${formatElapsed(d.durationSec!)}'),
      ],
    );
  }

  /// 대기·분석 중: 진행 표시(또는 아이콘) 아래 첫 문구를 크게, 나머지를 보통 크기로 (D-190).
  Widget _waiting(List<String> messages, {IconData? icon, Widget? action}) {
    return PageCard(
      padding: const EdgeInsets.all(32),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 380),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (icon == null) const BigSpinner() else Icon(icon, size: 64, color: progressColor),
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
            if (action != null) ...[const SizedBox(height: 24), action],
          ],
        ),
      ),
    );
  }

  /// 2.8 완료 (관리자). 고정한 것이 없을 때만 여기서 그린다 (있으면 결과 화면).
  Widget _completion(BuildContext context, VideoDetail d) {
    final none = (d.candidateTotal ?? 0) == 0;
    return StateCard(
      icon: none ? Icons.search : Icons.check_circle_outline,
      title: completionMessage(d),
      messages: [if (none) '이 영상에서는 확인할 후보 구간을 찾지 못했습니다.'],
      // 버튼 없이 안내만 둔다. 목록으로는 상단 메뉴로 간다 (D-190)
    );
  }

  /// 관리자의 [영상 올리기]. 같은 사건의 업로드 화면으로 간다. 사건을 아직 모르면 두지 않는다.
  Widget? _uploadButton() {
    final c = ref.watch(caseOfVideoProvider).value?[_id];
    if (c == null) return null;
    return FilledButton(
      style: largeButtonStyle,
      onPressed: () => context.go('/cases/${c.id}/upload'),
      child: const Text('영상 올리기'),
    );
  }

  Widget _failure(BuildContext context, VideoDetail d) {
    final notice = failureNotice(d, admin: _admin);
    final upload = notice.action == FailureAction.upload ? _uploadButton() : null;
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
        ?upload,
      ],
    );
  }
}

/// 진행도 4단계 표시줄 (07장 2.5, D-204). 지난 단계는 체크, 지금 단계는 진하게.
class _ProgressSteps extends StatelessWidget {
  const _ProgressSteps({required this.current});

  final int current;

  @override
  Widget build(BuildContext context) {
    Widget step(int i) {
      final done = i < current;
      final on = i == current;
      return Semantics(
        selected: on,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          spacing: 8,
          children: [
            Container(
              width: 28,
              height: 28,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: on || done ? pointColor : offWhiteColor,
                border: Border.all(color: on || done ? pointColor : progressColor, width: 1.5),
              ),
              child: done
                  ? const Icon(Icons.check, size: 16, color: offWhiteColor)
                  : Text(
                      '${i + 1}',
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: on ? offWhiteColor : subColor),
                    ),
            ),
            Text(
              progressSteps[i],
              style: TextStyle(
                fontSize: 15,
                fontWeight: on ? FontWeight.w700 : FontWeight.w500,
                color: on ? pointColor : (done ? inkColor : subColor),
              ),
            ),
          ],
        ),
      );
    }

    final narrow = isNarrow(context);
    return PageCard(
      padding: EdgeInsets.symmetric(horizontal: narrow ? 16 : 28, vertical: 18),
      child: narrow
          ? Wrap(spacing: 16, runSpacing: 10, children: [for (var i = 0; i < progressSteps.length; i++) step(i)])
          : Row(
              children: [
                for (var i = 0; i < progressSteps.length; i++) ...[
                  if (i > 0)
                    Expanded(
                      child: Container(
                        height: 2,
                        margin: const EdgeInsets.symmetric(horizontal: 16),
                        color: i <= current ? pointColor : lineColor,
                      ),
                    ),
                  step(i),
                ],
              ],
            ),
    );
  }
}
