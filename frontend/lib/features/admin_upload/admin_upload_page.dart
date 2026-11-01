import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/api/demo_api.dart';
import '../../core/browser/browser.dart';
import '../../core/constants.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';
import '../cases/case_link_page.dart';
import 'agreement_text.dart';
import 'upload_rules.dart';

enum _Step { agreement, upload }

/// 2.4 관리자 업로드. 관리자 계정으로 사건 관계자 연결 뒤, 또는 목록의 영상 없는 사건을 눌러 들어온다 (D-204, D-211).
/// 위탁계약 동의 → 파일 업로드 두 단계를 한 화면에서 차례로 바꾼다 (D-147).
class AdminUploadPage extends ConsumerStatefulWidget {
  const AdminUploadPage({super.key, required this.caseId});

  final int caseId;

  @override
  ConsumerState<AdminUploadPage> createState() => _AdminUploadPageState();
}

class _AdminUploadPageState extends ConsumerState<AdminUploadPage> {
  _Step _step = _Step.agreement;

  /// 업로드가 끝내 실패했을 때의 안내. 동의 단계 위에 보이고, 다시 올리면 동의부터 다시 받는다 (07장 2.4).
  String? _failure;

  /// 머리에 보일 피해자 이름 (22번). 못 읽으면 비워 둔다.
  String? _victimName;

  final _checks = {for (final c in agreementChecks) c.$1: false};
  final _bodyScroll = ScrollController();

  PickedFile? _file;
  String? _fileError;
  final _recording = TextEditingController();
  DateTime? _recordingPicked;
  String? _recordingError;

  bool _uploading = false;
  double? _progress;
  bool _warmupSent = false;

  @override
  void initState() {
    super.initState();
    requireAdmin(context, ref);
    _loadCase();
  }

  @override
  void dispose() {
    _bodyScroll.dispose();
    _recording.dispose();
    super.dispose();
  }

  Api get _api => ref.read(apiProvider);

  /// 머리의 "피해자 ○○"만 쓴다. 사건이 없으면 6번이 `CASE_NOT_FOUND`로 알려 준다.
  Future<void> _loadCase() async {
    try {
      final cases = await _api.cases(); // 22
      final found = cases.where((c) => c.id == widget.caseId);
      if (mounted && found.isNotEmpty) setState(() => _victimName = found.first.victimName);
    } catch (_) {
      // 이름 없이 그린다
    }
  }

  /// 녹화 시작 시각을 달력 → 시각 선택창 순서로 고른다. 직접 치는 칸은 없다.
  /// 고르면 "YYYY-MM-DD HH:mm:ss"로 칸을 채우고, 6번에 보낼 값은 지금처럼 [parseRecordingStart]가 만든다 (D-85, D-190).
  Future<void> _pickRecording() async {
    final now = DateTime.now();
    final current = _recordingPicked;
    final date = await showDialog<DateTime>(
      context: context,
      builder: (_) => _DateDialog(initial: current ?? now, last: now),
    );
    if (date == null || !mounted) return;
    final time = await showDialog<Duration>(
      context: context,
      builder: (_) => _TimeDialog(
        initial: current == null
            ? Duration.zero
            : Duration(hours: current.hour, minutes: current.minute, seconds: current.second),
      ),
    );
    if (time == null || !mounted) return;
    final picked = DateTime(date.year, date.month, date.day).add(time);
    String two(int n) => n.toString().padLeft(2, '0');
    setState(() {
      _recordingPicked = picked;
      _recording.text =
          '${picked.year}-${two(picked.month)}-${two(picked.day)} ${two(picked.hour)}:${two(picked.minute)}:${two(picked.second)}';
      _recordingError = null;
    });
  }

  void _agree() {
    // 서버를 부르지 않는다. 체크 값은 6번 요청에 함께 싣는다 (D-147)
    setState(() {
      _failure = null;
      _step = _Step.upload;
    });
  }

  Future<void> _pickFile() async {
    final file = await ref.read(browserProvider).pickFile(uploadExtensions);
    if (file == null || !mounted) return;
    setState(() {
      _fileError = checkUploadFile(file.name, file.size);
      _file = _fileError == null ? file : null;
    });
  }

  Future<void> _upload() async {
    final file = _file;
    if (file == null || _uploading) return;
    final (recordingAt, recordingError) = parseRecordingStart(_recording.text, DateTime.now());
    setState(() => _recordingError = recordingError);
    if (recordingError != null) return;

    setState(() => _uploading = true); // 버튼을 바로 막는다
    // 백엔드 연결 필요: 6번 업로드 URL 발급 → S3 PUT → 16번 GPU 켜기 → 7번 완료 알림
    await backendNotice(context, ref, '업로드');
    if (!mounted) return;
    final int videoId;
    final String uploadUrl;
    try {
      (:videoId, :uploadUrl) = await _api.presignUpload(
        widget.caseId,
        filename: file.name,
        sizeBytes: file.size,
        recordingStartedAt: recordingAt,
        agreement: {'version': agreementVersion, ..._checks},
      ); // 6
    } catch (e) {
      _onPresignError(errorCode(e));
      return;
    }

    final browser = ref.read(browserProvider);
    final started = DateTime.now();
    // 데모는 S3가 없어 올린 것으로 본다
    final status = uploadUrl == demoUploadUrl
        ? 200
        : await browser.putFile(
            uploadUrl,
            file,
            headers: const {'If-None-Match': '*'}, // 서명에 들어 있다 (D-100)
            onProgress: (sent, total) {
              if (!mounted) return;
              setState(() => _progress = total > 0 ? sent / total : null);
              final left = remainingUploadTime(sent, total, DateTime.now().difference(started));
              if (!_warmupSent && left != null && left <= warmupThreshold) {
                _warmupSent = true;
                _api.warmup(videoId).catchError((_) {}); // 16, 실패해도 무시 (D-62)
              }
            },
          );
    if (!mounted) return;

    switch (putOutcome(status)) {
      case PutOutcome.ok:
        await _complete(videoId);
      case PutOutcome.rejected:
        _fail('업로드가 거절됐습니다. 다시 올려 주세요.');
      case PutOutcome.forbidden:
        browser.log('S3 PUT 403 — If-None-Match 헤더 누락 여부 확인 (D-100)');
        _fail('업로드할 수 없습니다. 다시 올려 주세요.');
      case PutOutcome.interrupted:
        _fail('업로드가 중단됐습니다. 다시 올려 주세요.');
    }
  }

  void _onPresignError(String code) {
    if (!mounted) return;
    setState(() => _uploading = false);
    if (code == 'AGREEMENT_REQUIRED') {
      // 동의 단계로 돌아간다. 영상 행은 만들어지지 않았다 (D-147)
      showMessage(context, errorMessage(code));
      setState(() {
        _checks.updateAll((_, _) => false);
        _step = _Step.agreement;
      });
    } else if (code == 'UNSUPPORTED_FILE_TYPE' || code == 'FILE_TOO_LARGE') {
      setState(() {
        _fileError = code == 'FILE_TOO_LARGE' ? uploadTooLargeMessage : unsupportedUploadMessage;
        _file = null;
      });
    } else {
      handleCommonError(context, ApiException(0, code)); // CASE_NOT_FOUND면 목록으로
    }
  }

  /// S3가 200을 주면 7번. 500이면 같은 요청을 다시 보낸다 (두 번 불러도 된다, 05장 7번).
  Future<void> _complete(int videoId) async {
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        await _api.completeUpload(videoId); // 7
        if (!mounted) return;
        refreshSession(ref);
        showMessage(context, '업로드가 끝났습니다.');
        redirectTo(context, '/videos/$videoId'); // 영상 상태 화면으로 (07장 2.4)
        return;
      } catch (e) {
        final code = errorCode(e);
        if (code != 'INTERNAL_ERROR' && code != networkErrorCode) break;
        await Future<void>.delayed(const Duration(seconds: 2));
      }
    }
    if (mounted) {
      setState(() => _uploading = false);
      showMessage(context, errorMessage('INTERNAL_ERROR'));
    }
  }

  /// 업로드가 끊기거나 거절되면 안내를 띄우고 동의 단계로 돌아간다.
  /// 다시 올리면 6번부터 다시 부르므로 동의도 다시 받는다 (07장 2.4, 05장 6번).
  void _fail(String message) {
    if (!mounted) return;
    setState(() {
      _failure = message;
      _uploading = false;
      _progress = null;
      _warmupSent = false;
      _file = null;
      _checks.updateAll((_, _) => false);
      _step = _Step.agreement;
    });
  }

  @override
  Widget build(BuildContext context) {
    final failure = _failure;
    final victim = _victimName;
    return PageFrame(
      maxWidth: 1200,
      // "영상 올리기 | 피해자 ○○ | 위탁계약 동의 완료" (D-211). 열람기한은 업로드가 끝난 뒤에 생기므로 넣지 않는다
      eyebrow: '영상 올리기',
      eyebrowNotes: [if (victim != null) '피해자 $victim', if (_step == _Step.upload) '위탁계약 동의 완료'],
      title: 'CCTV 영상 올리기',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (failure != null) ...[_Message(failure), const SizedBox(height: 16)],
          switch (_step) {
            _Step.agreement => _agreementStep(context),
            _Step.upload => _uploadStep(context),
          },
        ],
      ),
    );
  }

  Widget _agreementStep(BuildContext context) {
    final allChecked = _checks.values.every((v) => v);
    return PageCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(agreementNoticeTitle, style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          const Text(agreementNotice, style: TextStyle(fontSize: 15, height: 1.6)),
          const SizedBox(height: 18),
          // 포커스를 받으면 방향키로 스크롤된다 (07장 3.5)
          Container(
            height: 320,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: lineColor, width: 1.5),
            ),
            child: Scrollbar(
              controller: _bodyScroll,
              thumbVisibility: true,
              child: SingleChildScrollView(
                controller: _bodyScroll,
                primary: false,
                padding: const EdgeInsets.all(16),
                child: const SelectableText(agreementBody, style: TextStyle(fontSize: 14, height: 1.6)),
              ),
            ),
          ),
          const SizedBox(height: 12),
          for (final (key, label) in agreementChecks)
            CheckboxListTile(
              value: _checks[key],
              onChanged: (v) => setState(() => _checks[key] = v ?? false),
              title: Text(label, style: const TextStyle(fontSize: 15)),
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
            ),
          const SizedBox(height: 18),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(onPressed: allChecked ? _agree : null, child: const Text('동의하고 영상 선택하기')),
          ),
        ],
      ),
    );
  }

  Widget _uploadStep(BuildContext context) {
    final file = _file;
    final progress = _progress;
    const label = TextStyle(fontSize: 14, fontWeight: FontWeight.w600);
    return PageCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text.rich(
            TextSpan(
              text: '차가 ',
              children: [
                TextSpan(
                  text: '이미 주차된 뒤',
                  style: TextStyle(fontWeight: FontWeight.w600),
                ),
                TextSpan(text: '의 장면부터 영상을 잘라서 올려주세요.'),
              ],
            ),
            style: TextStyle(fontSize: 15, height: 1.6),
          ),
          const SizedBox(height: 18),
          const Text('영상 파일', style: label),
          const SizedBox(height: 6),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              OutlinedButton(onPressed: _uploading ? null : _pickFile, child: const Text('파일 선택')),
              Text(file?.name ?? '선택한 파일이 없습니다.', style: const TextStyle(fontSize: 15)),
            ],
          ),
          const SizedBox(height: 6),
          const SmallText('.mp4 .avi .mkv .mov · 최대 5GB'),
          if (_fileError != null) ...[
            const SizedBox(height: 6),
            Text(_fileError!, style: const TextStyle(fontSize: 14, color: failColor)),
          ],
          const SizedBox(height: 18),
          const Text('녹화 시작 시각 (선택)', style: label),
          const SizedBox(height: 6),
          SizedBox(
            width: 320,
            child: TextField(
              controller: _recording,
              enabled: !_uploading,
              readOnly: true, // 직접 치지 않고 달력·시계로 고른다
              onTap: _pickRecording,
              mouseCursor: SystemMouseCursors.click,
              decoration: InputDecoration(
                hintText: '눌러서 날짜·시각 선택',
                errorText: _recordingError,
                suffixIcon: _recording.text.isEmpty
                    ? const Icon(Icons.calendar_today_outlined)
                    : IconButton(
                        tooltip: '녹화 시작 시각 지우기',
                        icon: const Icon(Icons.close),
                        onPressed: _uploading
                            ? null
                            : () => setState(() {
                                _recording.clear();
                                _recordingPicked = null;
                                _recordingError = null;
                              }),
                      ),
              ),
            ),
          ),
          const SizedBox(height: 6),
          const SmallText('영상 첫 장면의 실제 날짜·시각입니다.'),
          if (_uploading) ...[
            const SizedBox(height: 18),
            Text(progress == null ? '업로드를 준비하고 있습니다.' : '올리는 중 ${(progress * 100).floor()}%', style: label),
            const SizedBox(height: 8),
            Container(
              height: 12,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: inkColor, width: 1.5),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: LinearProgressIndicator(value: progress, minHeight: 12, backgroundColor: offWhiteColor),
              ),
            ),
          ],
          const SizedBox(height: 18),
          Wrap(
            spacing: 12,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              FilledButton(onPressed: file == null || _uploading ? null : _upload, child: const Text('업로드')),
              const SmallText('업로드가 끝나면 영상 상태 화면으로 넘어갑니다.'),
            ],
          ),
        ],
      ),
    );
  }
}

/// 업로드 화면 맨 위 오류 안내 상자. 빨강 테두리 (캔버스 2.4).
class _Message extends StatelessWidget {
  const _Message(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
    decoration: BoxDecoration(
      color: const Color(0xFFFCEEEE),
      borderRadius: BorderRadius.circular(cardRadius),
      border: Border.all(color: failColor, width: 1.5),
    ),
    child: Text(text, style: const TextStyle(fontSize: 15, height: 1.5)),
  );
}

/// 녹화 시작 시각 선택창. 오전/오후 · 시(1~12) · 분 · 초를 각각 고른다 (D-190).
/// 돌려주는 값은 그날 0시부터 지난 시간이다.
class _TimeDialog extends StatefulWidget {
  const _TimeDialog({required this.initial});

  final Duration initial;

  @override
  State<_TimeDialog> createState() => _TimeDialogState();
}

class _TimeDialogState extends State<_TimeDialog> {
  late bool _pm = widget.initial.inHours >= 12;
  late int _hour12 = widget.initial.inHours % 12 == 0 ? 12 : widget.initial.inHours % 12; // 1~12
  late int _minute = widget.initial.inMinutes % 60;
  late int _second = widget.initial.inSeconds % 60;

  Duration get _value => Duration(hours: _hour12 % 12 + (_pm ? 12 : 0), minutes: _minute, seconds: _second);

  Widget _pick<T>(String label, T value, List<(T, String)> items, ValueChanged<T> onChanged) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(label, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: subColor)),
      const SizedBox(height: 4),
      DropdownButton<T>(
        value: value,
        menuMaxHeight: 320,
        items: [for (final (v, text) in items) DropdownMenuItem(value: v, child: Text(text))],
        onChanged: (v) {
          if (v != null) setState(() => onChanged(v));
        },
      ),
    ],
  );

  @override
  Widget build(BuildContext context) {
    String two(int n) => n.toString().padLeft(2, '0');
    final sixty = [for (var i = 0; i < 60; i++) (i, two(i))];
    return AlertDialog(
      title: const Text('녹화 시작 시각'),
      // 네 칸을 한 줄로 (줄바꿈하지 않는다)
      content: Row(
        mainAxisSize: MainAxisSize.min,
        spacing: 20,
        children: [
          _pick('오전/오후', _pm, const [(false, '오전'), (true, '오후')], (v) => _pm = v),
          _pick('시', _hour12, [for (var h = 1; h <= 12; h++) (h, '$h')], (v) => _hour12 = v),
          _pick('분', _minute, sixty, (v) => _minute = v),
          _pick('초', _second, sixty, (v) => _second = v),
        ],
      ),
      actions: [
        OutlinedButton(onPressed: () => Navigator.pop(context), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(context, _value), child: const Text('확인')),
      ],
    );
  }
}

/// 녹화 시작 날짜 선택창. 왼쪽 큰 날짜 머리와 직접 입력 모드 없이 달력만 둔다 (D-190).
class _DateDialog extends StatefulWidget {
  const _DateDialog({required this.initial, required this.last});

  final DateTime initial;

  /// 고를 수 있는 마지막 날 (오늘).
  final DateTime last;

  @override
  State<_DateDialog> createState() => _DateDialogState();
}

class _DateDialogState extends State<_DateDialog> {
  late DateTime _date = widget.initial;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('녹화 시작 날짜'),
      content: SizedBox(
        width: 360,
        height: 360, // 달력 6주가 잘리지 않는 높이
        child: CalendarDatePicker(
          initialDate: _date,
          firstDate: DateTime(2000),
          lastDate: widget.last,
          onDateChanged: (d) => setState(() => _date = d),
        ),
      ),
      actions: [
        OutlinedButton(onPressed: () => Navigator.pop(context), child: const Text('취소')),
        FilledButton(onPressed: () => Navigator.pop(context, _date), child: const Text('확인')),
      ],
    );
  }
}
