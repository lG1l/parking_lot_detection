import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
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

/// 2.7 후보 확인. 두 탭(후보군·파싱 실패)을 묶음 단위로 보고 [고정]으로 사건 지점을 고정한다.
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
  String? _filename;
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
      final results = await Future.wait([_api.batch(_id, list: _tab), _api.pins(_id)]);
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
      _filename = d.originalFilename;
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

  void _setPins(List<PinnedIncident> pins) => setState(() => _pinned = pins.map((p) => p.candidateClipId).toSet());

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
    // 확인창 없이 바로 고정한다. [확인 완료] 전까지 [고정 해제]로 풀 수 있다 (D-190)
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

  Future<void> _unpin(CandidateClip c) async {
    // 확인창 없이 바로 해제한다. [확인 완료] 전까지 다시 [고정]할 수 있다 (D-190)
    // 백엔드 연결 필요: 20번 사건 지점 고정 해제
    await backendNotice(context, ref, '고정 해제');
    setState(() => _pinning.add(c.candidateClipId));
    try {
      _setPins(await _api.unpin(_id, c.candidateClipId)); // 20, 응답이 곧 남은 고정 목록
    } catch (e) {
      _onError(e);
    } finally {
      if (mounted) setState(() => _pinning.remove(c.candidateClipId));
    }
  }

  /// 마지막 페이지의 [확인 완료]: 확인창을 띄운 뒤 13번으로 이 탭의 마지막 묶음을 넘긴다 (D-190).
  /// 다른 탭도 끝났으면 영상 전체가 끝나(exhausted) 완료 또는 결과 화면으로 간다.
  /// 다른 탭에 후보가 남았으면 이 탭만 끝나고, 이 페이지에 "모두 확인했습니다" 안내가 뜬다.
  Future<void> _endTab() async {
    final whole = needsLastBatchConfirm(_lists!, _tab);
    final other = CandidateList.other(_tab) == CandidateList.main ? '후보' : '점수 미산출';
    final ok = whole
        ? await confirm(
            context,
            '모든 후보를 확인한 것으로 끝냅니다. 끝낸 뒤에는 더는 [고정]을 누를 수 없습니다. 고정한 장면은 결과 화면에서 볼 수 있습니다.',
            title: '후보 확인을 끝낼까요?',
            okLabel: '끝내기',
          )
        : await confirm(
            context,
            '이 목록의 후보를 모두 확인한 것으로 끝냅니다. $other 탭에 확인할 후보가 남아 있습니다.',
            title: '이 목록의 확인을 끝낼까요?',
            okLabel: '끝내기',
          );
    if (ok && mounted) await _fetchNext();
  }

  Future<void> _fetchNext() async {
    final b = _batch!;
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
      '끝낸 뒤에는 더는 [고정]을 누를 수 없습니다. 고정한 장면은 결과 화면에서 볼 수 있습니다.',
      title: '후보 확인을 끝낼까요?',
      okLabel: '끝내기',
    )) {
      return;
    }
    if (!mounted) return;
    // 백엔드 연결 필요: 17번 확인 끝내기
    await backendNotice(context, ref, '확인 완료');
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
      eyebrow: '후보 확인',
      title: _filename ?? '후보 확인',
      scrollBody: !_fixedLayout(context),
      child: batch == null ? const Center(child: CircularProgressIndicator()) : _body(context, batch),
    );
  }

  /// 창이 충분히 높으면 위쪽(제목·탭·안내·묶음 준비 상자)과 아래 이동 줄을 고정하고 영상 목록만 스크롤한다 (D-190).
  /// 낮은 창에서는 고정 부분이 화면을 다 차지하므로 지금처럼 화면 전체를 스크롤한다.
  bool _fixedLayout(BuildContext context) => MediaQuery.sizeOf(context).height >= 640;

  Widget _body(BuildContext context, Batch batch) {
    final lists = _lists!;
    final tab = lists[_tab]!;
    final unavailable = unavailableMessage(batch);
    final doneMessage = tabDoneMessage(lists, _tab);
    final other = CandidateList.other(_tab);
    final fixed = _fixedLayout(context);
    // 묶음의 영상(최대 10개)과 탭을 다 봤을 때 안내. 창이 충분히 높으면 이 부분만 스크롤한다
    final clips = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _grid(batch.candidates),
        if (doneMessage != null && batch.batchNo == lists[_tab]!.latestBatchNo) ...[
          const SizedBox(height: 12),
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 8,
            children: [
              SmallText(doneMessage),
              if (tabEnabled(lists, other))
                TextButton(onPressed: () => _switchTab(other), child: const Text('다른 탭 보기')),
            ],
          ),
        ],
      ],
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _tabs(lists),
        const SizedBox(height: 10),
        Text(
          _tab == CandidateList.main
              ? '점수(0~100)는 차량 접촉 근거가 얼마나 뚜렷한지를 나타내며, 사고가 났을 확률이 아닙니다.'
              : 'AI가 점수를 내지 못한 후보입니다. 사건 가능성이 낮다는 뜻은 아닙니다.',
          style: const TextStyle(fontSize: 15, color: subColor),
        ),
        const SizedBox(height: 12),
        if (_status == VideoStatus.batchRunning) ...[
          const PageCard(
            padding: EdgeInsets.all(24),
            child: Column(
              children: [
                BigSpinner(),
                SizedBox(height: 18),
                Text('다음 영상 묶음을 만드는 중입니다.', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
                SizedBox(height: 8),
                Text(
                  '그동안 [◀ 이전]으로 앞 묶음을 다시 보고 [고정]을 누를 수 있습니다.',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 15, height: 1.6, color: subColor),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
        ],
        if (unavailable != null) ...[
          // 작은 안내 띠 (D-190)
          Align(
            alignment: Alignment.centerLeft,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: offWhiteColor,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: lineColor),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                spacing: 8,
                children: [
                  const Icon(Icons.videocam_off_outlined, size: 16, color: subColor),
                  Flexible(
                    child: Text(unavailable, style: const TextStyle(fontSize: 13, color: subColor)),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 14),
        ],
        if (fixed) Expanded(child: SingleChildScrollView(child: clips)) else clips,
        const SizedBox(height: 12),
        // 왼쪽 아래 열람기한, 오른쪽 아래 묶음 이동 (D-190)
        if (isNarrow(context))
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            spacing: 12,
            children: [_navigation(batch, tab), SmallText(resultExpiresText(_viewExpiresAt))],
          )
        else
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              // 열람기한이 남는 폭을 쓰고, 남은 후보 ~ [다음 ▶]·[확인 완료]는 한 줄로 오른쪽 끝에 붙인다
              Expanded(child: SmallText(resultExpiresText(_viewExpiresAt))),
              const SizedBox(width: 16),
              _navigation(batch, tab),
            ],
          ),
      ],
    );
  }

  /// 밑줄형 탭 두 개 (캔버스 2.7). 고른 탭은 남색 밑줄.
  Widget _tabs(Map<String, ListSummary> lists) {
    Widget tabButton(String t) {
      final selected = t == _tab;
      final enabled = tabEnabled(lists, t);
      return Semantics(
        selected: selected,
        button: true,
        child: InkWell(
          onTap: enabled && !_busy ? () => _switchTab(t) : null,
          child: Container(
            constraints: const BoxConstraints(minHeight: 44),
            padding: const EdgeInsets.symmetric(horizontal: 18),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: selected ? pointColor : Colors.transparent, width: 3)),
            ),
            child: Text(
              tabLabel(lists, t),
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: selected ? inkColor : (enabled ? noteColor : progressColor),
              ),
            ),
          ),
        ),
      );
    }

    return Container(
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFFD6D6D2), width: 1.5)),
      ),
      child: Row(
        children: [
          for (final t in [CandidateList.main, CandidateList.parseFailed]) tabButton(t),
        ],
      ),
    );
  }

  /// 넓으면 3열, 좁아지면 2열·1열.
  Widget _grid(List<CandidateClip> candidates) {
    const gap = 14.0;
    return LayoutBuilder(
      builder: (context, c) {
        final columns = c.maxWidth >= 900 ? 3 : (c.maxWidth >= 560 ? 2 : 1);
        final width = (c.maxWidth - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [for (final clip in candidates) SizedBox(width: width, child: _candidateCard(clip))],
        );
      },
    );
  }

  Widget _candidateCard(CandidateClip c) {
    final pinned = _pinned.contains(c.candidateClipId);
    final score = c.vlmScore;
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: offWhiteColor,
        borderRadius: BorderRadius.circular(10),
        // 고정한 후보는 굵은 남색 테두리 (캔버스 2.7)
        border: pinned ? Border.all(color: pointColor, width: 3) : Border.all(color: inkColor, width: 1.5),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              // 순위 대신 점수만 진하게 (D-190). 점수 미산출 탭은 "-"
              Text(
                '점수: ${score == null ? '-' : score.round()}',
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: inkColor),
              ),
              const Spacer(),
              if (pinned)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: pointColor, borderRadius: BorderRadius.circular(cardRadius)),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.push_pin, size: 14, color: offWhiteColor),
                      SizedBox(width: 4),
                      Text(
                        '확정됨',
                        style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: offWhiteColor),
                      ),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          ClipPlayer(url: c.clipUrl, onUrlExpired: _onUrlExpired),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: SmallText('${formatElapsed(c.startSec)} ~ ${formatElapsed(c.endSec)}')),
              if (pinned)
                OutlinedButton(
                  onPressed: _pinning.contains(c.candidateClipId) ? null : () => _unpin(c),
                  child: const Text('고정 해제'),
                )
              else
                FilledButton(
                  onPressed: _pinning.contains(c.candidateClipId) ? null : () => _pin(c),
                  child: const Text('고정'),
                ),
            ],
          ),
        ],
      ),
    );
  }

  /// 아래 오른쪽 줄: 남은 후보 · [◀ 이전] · 묶음 n / m · [다음 ▶] · [확인 완료] (캔버스 2.7).
  Widget _navigation(Batch batch, ListSummary tab) {
    final latest = tab.latestBatchNo ?? batch.batchNo;
    final lastPage = isLastPage(batch, tab, _status!);
    final showFetch = canFetchNext(batch, tab, _status!) && !lastPage;
    return Wrap(
      alignment: WrapAlignment.end,
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: 14,
      runSpacing: 8,
      children: [
        SmallText('남은 후보 ${tab.remaining}건'),
        OutlinedButton(
          onPressed: _busy || batch.batchNo <= 1 ? null : () => _run(() => _loadBatch(batchNo: batch.batchNo - 1)),
          child: const Text('◀ 이전'),
        ),
        Text('묶음 ${batch.batchNo} / $latest', style: const TextStyle(fontWeight: FontWeight.w600)),
        if (showFetch)
          // 이름은 [다음 ▶]과 같다. 받은 묶음이 끝이면 13번으로 새 묶음을 받는다 (D-190)
          OutlinedButton(onPressed: _busy ? null : _fetchNext, child: const Text('다음 ▶'))
        else
          OutlinedButton(
            onPressed: _busy || batch.batchNo >= latest
                ? null
                : () => _run(() => _loadBatch(batchNo: batch.batchNo + 1)),
            child: const Text('다음 ▶'),
          ),
        // [확인 완료]는 늘 보인다 (D-190). 마지막 페이지면 이 탭을 끝내고(13번),
        // 그 전에는 고정이 1개 이상일 때 영상 전체를 끝낸다(17번). 둘 다 아니면 막는다.
        Tooltip(
          message: lastPage || _pinned.isNotEmpty ? '' : '장면을 고정했거나 마지막 묶음까지 보면 누를 수 있습니다',
          child: FilledButton(
            onPressed: _busy
                ? null
                : lastPage
                ? _endTab
                : _pinned.isNotEmpty
                ? _finish
                : null,
            child: const Text('확인 완료'),
          ),
        ),
      ],
    );
  }
}
