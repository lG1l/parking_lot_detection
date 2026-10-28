import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/constants.dart';
import '../../core/format.dart';
import '../../core/models/analysis.dart';
import '../../core/models/video.dart';
import '../../core/widgets/clip_player.dart';
import '../../core/widgets/common.dart';
import '../video_status/status_rules.dart';
import '../video_status/video_status_page.dart';
import 'batch_rules.dart';

/// 2.7 후보 확인. 두 탭(후보군·파싱 실패)을 묶음 단위로 보고 [찾음]으로 사건 지점을 고정한다.
class CandidatesPage extends ConsumerStatefulWidget {
  const CandidatesPage({super.key, required this.videoId});

  final String videoId;

  @override
  ConsumerState<CandidatesPage> createState() => _CandidatesPageState();
}

class _CandidatesPageState extends ConsumerState<CandidatesPage> {
  int get _id => int.parse(widget.videoId);
  Api get _api => ref.read(apiProvider);

  String? _status;
  String? _viewExpiresAt;
  String _tab = CandidateList.main; // 다시 들어오면 [후보] 탭부터 (07장 3.7)
  Batch? _batch;
  Map<String, ListSummary>? _lists;
  Set<int> _pinned = {};
  final Set<int> _pinning = {};
  bool _busy = false;
  Timer? _timer;
  DateTime? _lastUrlReload;

  @override
  void initState() {
    super.initState();
    _open();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  /// 9번으로 이 화면이 맞는지 보고, 12번(main)과 15번을 부른다.
  Future<void> _open() async {
    try {
      if (!await _loadStatus()) return;
      final results = await Future.wait([
        _api.batch(_id, list: _tab),
        _api.pins(_id),
      ]);
      if (!mounted) return;
      _showBatch(results[0] as Batch);
      _setPins(results[1] as List<PinnedIncident>);
    } catch (e) {
      _onError(e);
    }
  }

  /// 9번. 후보 확인 화면이 아니면 상태 화면으로 보내고 false.
  Future<bool> _loadStatus() async {
    final d = await _api.video(_id); // 9
    if (!mounted) return false;
    if (selectScreen(d) != StatusScreen.candidates) {
      goStatus(context, _id);
      return false;
    }
    setState(() {
      _status = d.status;
      _viewExpiresAt = d.viewExpiresAt;
    });
    _schedulePoll();
    return true;
  }

  /// 다음 묶음을 만드는 동안(batch_running) 9번을 주기적으로 불러 ready가 되면 연다.
  void _schedulePoll() {
    _timer?.cancel();
    if (_status != VideoStatus.batchRunning) return;
    _timer = Timer(pollInterval, () async {
      try {
        if (!await _loadStatus()) return;
        if (_status == VideoStatus.ready) await _loadBatch();
      } catch (e) {
        _onError(e);
      }
    });
  }

  void _showBatch(Batch b) {
    setState(() {
      _batch = b;
      _tab = b.list;
      _lists = b.lists;
    });
  }

  void _setPins(List<PinnedIncident> pins) =>
      setState(() => _pinned = pins.map((p) => p.candidateClipId).toSet());

  Future<void> _loadBatch({String? list, int? batchNo}) async {
    final b = await _api.batch(_id, list: list ?? _tab, batchNo: batchNo); // 12
    if (mounted) _showBatch(b);
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      _onError(e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _onError(Object e) {
    if (!mounted) return;
    if (handleCommonError(context, e)) return;
    final code = errorCode(e);
    switch (code) {
      case 'CLIP_NOT_FOUND' || 'NO_PINNED_INCIDENTS':
        _loadBatch().catchError(_onError); // 12번을 다시 불러 그린다
      case 'VALIDATION_FAILED':
        _tab = CandidateList.main;
        _api.batch(_id).then(_showBatch).catchError(_onError); // 쿼리 없이 다시
      case _ when needsStatusReload(code):
        goStatus(context, _id, expired: isExpiredCode(code));
    }
  }

  /// 재생 URL이 만료되면 보던 묶음을 다시 불러 새 URL을 받는다 (D-41). 연달아 부르지 않는다.
  void _onUrlExpired() {
    final last = _lastUrlReload;
    if (last != null && DateTime.now().difference(last) < const Duration(seconds: 10)) return;
    _lastUrlReload = DateTime.now();
    final b = _batch;
    if (b != null) _loadBatch(batchNo: b.batchNo).catchError(_onError);
  }

  Future<void> _pin(CandidateClip c) async {
    if (!await confirm(context, '이 장면을 사건 지점으로 고정합니다. 고정은 취소할 수 없습니다.', okLabel: '고정')) {
      return;
    }
    if (!mounted) return;
    // 백엔드 연결 필요: 14번 사건 지점 고정
    await backendNotice(context, ref, '고정');
    setState(() => _pinning.add(c.candidateClipId));
    try {
      _setPins(await _api.pin(_id, c.candidateClipId)); // 14, 응답이 곧 고정 목록
    } catch (e) {
      _onError(e);
    } finally {
      if (mounted) setState(() => _pinning.remove(c.candidateClipId));
    }
  }

  Future<void> _fetchNext() async {
    final b = _batch!;
    if (needsLastBatchConfirm(_lists!, _tab) &&
        !await confirm(
          context,
          '마지막 묶음입니다. 넘기면 후보 확인이 끝나고 더는 [찾음]을 누를 수 없습니다.',
          okLabel: '넘기기',
        )) {
      return;
    }
    if (!mounted) return;
    // 백엔드 연결 필요: 13번 다음 묶음 받기
    await backendNotice(context, ref, '다음 묶음 받기');
    await _run(() async {
      final r = await _api.nextBatch(_id, _tab, b.batchNo); // 13
      if (!mounted) return;
      setState(() {
        _status = r.status;
        _lists = r.lists;
      });
      switch (r.status) {
        case VideoStatus.ready:
          await _loadBatch();
        case VideoStatus.batchRunning:
          _schedulePoll();
        default:
          goStatus(context, _id); // exhausted → 완료 또는 결과 화면
      }
    });
  }

  Future<void> _finish() async {
    if (!await confirm(
      context,
      '후보 확인을 끝냅니다. 끝낸 뒤에는 더는 [찾음]을 누를 수 없습니다.',
      okLabel: '끝내기',
    )) {
      return;
    }
    if (!mounted) return;
    // 백엔드 연결 필요: 17번 확인 끝내기
    await backendNotice(context, ref, '확인 끝내기');
    await _run(() async {
      await _api.finish(_id); // 17
      if (mounted) redirectTo(context, '/videos/$_id/results');
    });
  }

  void _switchTab(String tab) {
    if (tab == _tab) return;
    _run(() => _loadBatch(list: tab)); // 탭을 바꿀 때는 12번만 (07장 2.7)
  }

  @override
  Widget build(BuildContext context) {
    final batch = _batch;
    return PageFrame(
      title: '후보 확인',
      maxWidth: 1100,
      actions: [
        if (_pinned.isNotEmpty)
          TextButton.icon(
            onPressed: _busy ? null : _finish,
            icon: const Icon(Icons.done_all),
            label: const Text('확인 끝내기'),
          ),
        // 서버를 부르지 않는다. 보던 묶음과 고정은 서버에 남아 있다 (D-110, D-111)
        const BackToListButton(label: '나중에 확인'),
      ],
      child: batch == null ? const Center(child: CircularProgressIndicator()) : _body(context, batch),
    );
  }

  Widget _body(BuildContext context, Batch batch) {
    final lists = _lists!;
    final tab = lists[_tab]!;
    final unavailable = unavailableMessage(batch);
    final doneMessage = tabDoneMessage(lists, _tab);
    final other = CandidateList.other(_tab);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(resultExpiresText(_viewExpiresAt)),
        const SizedBox(height: 4),
        const SmallText('확인한 내용은 저장되어 있습니다. 열람기한 안에 목록에서 다시 열어 이어서 확인할 수 있습니다.'),
        const SizedBox(height: 16),
        SegmentedButton<String>(
          segments: [
            for (final t in [CandidateList.main, CandidateList.parseFailed])
              ButtonSegment(value: t, label: Text(tabLabel(lists, t)), enabled: tabEnabled(lists, t)),
          ],
          selected: {_tab},
          showSelectedIcon: false,
          onSelectionChanged: _busy ? null : (s) => _switchTab(s.first),
        ),
        const SizedBox(height: 8),
        if (_tab == CandidateList.main)
          const SmallText('점수(0~100)는 차량 접촉 근거가 얼마나 뚜렷한지를 나타내며, 사고가 났을 확률이 아닙니다.')
        else
          const SmallText('AI 답변 형식이 맞지 않아 3번 다시 불러도 점수를 읽지 못한 후보를 모았습니다. 사건 가능성이 낮다는 뜻은 아닙니다.'),
        const SizedBox(height: 12),
        if (_status == VideoStatus.batchRunning)
          const Notice('다음 영상 묶음을 만드는 중입니다.', icon: Icons.hourglass_top),
        if (unavailable != null) Notice(unavailable, icon: Icons.videocam_off_outlined),
        for (final c in batch.candidates) _candidateCard(context, c),
        const SizedBox(height: 12),
        _navigation(batch, tab),
        if (doneMessage != null) ...[
          const SizedBox(height: 12),
          Notice(doneMessage),
          if (tabEnabled(lists, other))
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(onPressed: () => _switchTab(other), child: const Text('다른 탭 보기')),
            ),
        ],
      ],
    );
  }

  Widget _candidateCard(BuildContext context, CandidateClip c) {
    final pinned = _pinned.contains(c.candidateClipId);
    final score = c.vlmScore;
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Text('${c.rank}위', style: Theme.of(context).textTheme.titleMedium),
                if (score != null) ...[
                  const SizedBox(width: 12),
                  Text('점수 ${score.round()}'),
                ],
                const SizedBox(width: 12),
                SmallText('영상 시작부터 ${formatElapsed(c.startSec)} ~ ${formatElapsed(c.endSec)}'),
                const Spacer(),
                if (pinned) const Chip(label: Text('확정됨'), avatar: Icon(Icons.push_pin, size: 16)),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: pinned || _pinning.contains(c.candidateClipId) ? null : () => _pin(c),
                  child: const Text('찾음'),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ClipPlayer(url: c.clipUrl, onUrlExpired: _onUrlExpired),
          ],
        ),
      ),
    );
  }

  Widget _navigation(Batch batch, ListSummary tab) {
    final latest = tab.latestBatchNo ?? batch.batchNo;
    final showFetch = canFetchNext(batch, tab, _status!);
    return Wrap(
      alignment: WrapAlignment.center,
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 12,
      runSpacing: 8,
      children: [
        OutlinedButton(
          onPressed: _busy || batch.batchNo <= 1
              ? null
              : () => _run(() => _loadBatch(batchNo: batch.batchNo - 1)),
          child: const Text('◀ 이전'),
        ),
        Text('묶음 ${batch.batchNo} / $latest'),
        if (showFetch)
          FilledButton(onPressed: _busy ? null : _fetchNext, child: const Text('다음 묶음 받기'))
        else
          OutlinedButton(
            onPressed: _busy || batch.batchNo >= latest
                ? null
                : () => _run(() => _loadBatch(batchNo: batch.batchNo + 1)),
            child: const Text('다음 ▶'),
          ),
        Text('남은 후보 ${tab.remaining}건'),
      ],
    );
  }
}
