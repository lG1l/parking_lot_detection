import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api.dart';
import '../../core/constants.dart';
import '../../core/models/account.dart';
import '../../core/widgets/common.dart';
import 'status_rules.dart';
import 'video_status_page.dart';

/// 피해자 계정: 연결만 되고 관리자가 아직 영상을 올리기 전인 사건 (D-312).
/// 영상 상태 화면(2.5)과 같은 모양이고, 진행 표시 없이 문구만 보인다.
/// 8번을 5초마다 불러 이 사건에 영상이 생기면 그 영상의 상태 화면으로 간다.
class CaseWaitingPage extends ConsumerStatefulWidget {
  const CaseWaitingPage({super.key, required this.caseId});

  final int caseId;

  @override
  ConsumerState<CaseWaitingPage> createState() => _CaseWaitingPageState();
}

class _CaseWaitingPageState extends ConsumerState<CaseWaitingPage> {
  VideoCase? _case;
  bool _loaded = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(pollInterval, (_) => _checkVideo());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final cases = await ref.read(apiProvider).cases(); // 22
      if (!mounted) return;
      setState(() {
        _case = cases.where((c) => c.id == widget.caseId).firstOrNull;
        _loaded = true;
      });
      await _checkVideo();
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    }
  }

  /// 관리자가 업로드를 시작해 영상이 생겼으면 그 영상의 상태 화면으로 넘어간다.
  Future<void> _checkVideo() async {
    try {
      final videos = await ref.read(apiProvider).videos(); // 8
      final v = videos.where((v) => v.caseId == widget.caseId).firstOrNull;
      if (v != null && mounted) {
        _timer?.cancel();
        redirectTo(context, '/videos/${v.videoId}');
      }
    } catch (_) {
      // 다음 주기에 다시 본다
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = _case;
    final name = c?.name;
    return PageFrame(
      current: NavItem.videos,
      eyebrow: _loaded ? '영상 상태' : null,
      eyebrowNotes: c == null ? const [] : [c.counterpart(admin: false)],
      // 불러오는 동안은 제목을 비워 둔다. 영상이 없어 파일 이름 대신 사건 이름을 쓴다
      title: _loaded ? (name ?? '업로드 대기') : null,
      titleStrong: _loaded ? (name ?? '업로드 대기') : null,
      child: !_loaded
          ? const SizedBox.shrink()
          : c == null
          ? const WaitingCard(messages: ['사건을 찾을 수 없습니다.'], spinner: false)
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                StepBar(steps: progressSteps, current: 0),
                const SizedBox(height: 32),
                const WaitingCard(messages: beforeUploadMessages, spinner: false),
              ],
            ),
    );
  }
}
