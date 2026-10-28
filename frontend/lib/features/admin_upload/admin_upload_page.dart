import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/browser/browser.dart';
import '../../core/constants.dart';
import '../../core/widgets/common.dart';
import 'agreement_text.dart';
import 'upload_rules.dart';

/// 링크 오류 문구 (07장 2.4).
String uploadTokenMessage(String code) => code == 'UPLOAD_TOKEN_NOT_FOUND'
    ? '링크 주소가 올바르지 않습니다. 주소를 다시 확인해 주세요.'
    : '만료되거나 이미 사용이 완료된 링크입니다. 피해자에게 새 링크를 받아 주세요.';

bool _isTokenError(String code) => code.startsWith('UPLOAD_TOKEN_');

enum _Step { checking, agreement, upload, finished }

/// 2.4 관리자 업로드. 로그인 없이 링크의 token으로만 들어온다 (D-28).
/// 위탁계약 동의 → 파일 업로드 두 단계를 한 화면에서 차례로 바꾼다 (D-147).
class AdminUploadPage extends ConsumerStatefulWidget {
  const AdminUploadPage({super.key, required this.token});

  final String token;

  @override
  ConsumerState<AdminUploadPage> createState() => _AdminUploadPageState();
}

class _AdminUploadPageState extends ConsumerState<AdminUploadPage> {
  _Step _step = _Step.checking;

  /// 링크를 쓸 수 없거나 업로드가 끝내 실패했을 때의 안내. 있으면 이것만 보인다.
  String? _blocked;

  final _checks = {for (final c in agreementChecks) c.$1: false};
  final _bodyScroll = ScrollController();

  PickedFile? _file;
  String? _fileError;
  final _recording = TextEditingController();
  String? _recordingError;

  bool _uploading = false;
  double? _progress;
  bool _warmupSent = false;

  @override
  void initState() {
    super.initState();
    _checkToken();
  }

  @override
  void dispose() {
    _bodyScroll.dispose();
    _recording.dispose();
    super.dispose();
  }

  Api get _api => ref.read(apiProvider);

  Future<void> _checkToken() async {
    try {
      await _api.checkUploadToken(widget.token); // 5
      if (mounted) setState(() => _step = _Step.agreement);
    } catch (e) {
      final code = errorCode(e);
      if (!mounted) return;
      setState(() {
        _blocked = _isTokenError(code) ? uploadTokenMessage(code) : errorMessage(code);
      });
    }
  }

  void _agree() {
    // 서버를 부르지 않는다. 체크 값은 6번 요청에 함께 싣는다 (D-147)
    setState(() => _step = _Step.upload);
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
    final String uploadUrl;
    try {
      uploadUrl = await _api.presignUpload(
        widget.token,
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
    final status = await browser.putFile(
      uploadUrl,
      file,
      headers: const {'If-None-Match': '*'}, // 서명에 들어 있다 (D-100)
      onProgress: (sent, total) {
        if (!mounted) return;
        setState(() => _progress = total > 0 ? sent / total : null);
        final left = remainingUploadTime(sent, total, DateTime.now().difference(started));
        if (!_warmupSent && left != null && left <= warmupThreshold) {
          _warmupSent = true;
          _api.warmup(widget.token).catchError((_) {}); // 16, 실패해도 무시 (D-62)
        }
      },
    );
    if (!mounted) return;

    switch (putOutcome(status)) {
      case PutOutcome.ok:
        await _complete();
      case PutOutcome.rejected:
        _fail('업로드가 거절됐습니다. 피해자에게 새 링크를 받으세요.');
      case PutOutcome.forbidden:
        browser.log('S3 PUT 403 — If-None-Match 헤더 누락 여부 확인 (D-100)');
        _fail('업로드할 수 없습니다. 피해자에게 새 링크를 받아 주세요.');
      case PutOutcome.interrupted:
        _fail('업로드가 중단됐습니다. 이 링크는 다시 쓸 수 없으니 피해자에게 새 링크를 받아 주세요.');
    }
  }

  void _onPresignError(String code) {
    if (!mounted) return;
    setState(() => _uploading = false);
    if (_isTokenError(code)) {
      _fail(uploadTokenMessage(code));
    } else if (code == 'AGREEMENT_REQUIRED') {
      // 동의 단계로 돌아간다. 링크는 쓴 것이 되지 않았다 (D-147)
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
      showMessage(context, errorMessage(code));
    }
  }

  /// S3가 200을 주면 7번. 500이면 같은 요청을 다시 보낸다 (두 번 불러도 된다, 05장 7번).
  Future<void> _complete() async {
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        await _api.completeUpload(widget.token); // 7
        if (mounted) setState(() => _step = _Step.finished);
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

  void _fail(String message) {
    if (mounted) setState(() => _blocked = message);
  }

  @override
  Widget build(BuildContext context) {
    final blocked = _blocked;
    return PageFrame(
      title: '영상 업로드',
      homeLink: false,
      showBack: false,
      maxWidth: 800,
      child: blocked != null
          ? Notice(blocked, icon: Icons.error_outline)
          : switch (_step) {
              _Step.checking => const Center(child: CircularProgressIndicator()),
              _Step.agreement => _agreementStep(context),
              _Step.upload => _uploadStep(context),
              _Step.finished => const Notice(
                '업로드가 끝났습니다. 이 창을 닫아도 됩니다.',
                icon: Icons.check_circle_outline,
              ),
            },
    );
  }

  Widget _agreementStep(BuildContext context) {
    final allChecked = _checks.values.every((v) => v);
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(agreementNoticeTitle, style: text.titleLarge),
        const SizedBox(height: 8),
        const Text(agreementNotice),
        const SizedBox(height: 16),
        // 포커스를 받으면 방향키로 스크롤된다 (07장 3.5)
        Container(
          height: 320,
          decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor)),
          child: Scrollbar(
            controller: _bodyScroll,
            thumbVisibility: true,
            child: SingleChildScrollView(
              controller: _bodyScroll,
              primary: false,
              padding: const EdgeInsets.all(16),
              child: const SelectableText(agreementBody),
            ),
          ),
        ),
        const SizedBox(height: 16),
        for (final (key, label) in agreementChecks)
          CheckboxListTile(
            value: _checks[key],
            onChanged: (v) => setState(() => _checks[key] = v ?? false),
            title: Text(label),
            controlAffinity: ListTileControlAffinity.leading,
          ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: allChecked ? _agree : null,
          child: const Text('동의하고 영상 선택하기'),
        ),
      ],
    );
  }

  Widget _uploadStep(BuildContext context) {
    final file = _file;
    final progress = _progress;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Notice('차가 이미 주차된 뒤의 장면부터 영상을 잘라서 올려 주세요. 녹화기의 MP4·AVI 내보내기를 쓰면 됩니다.'),
        const SizedBox(height: 16),
        Row(
          children: [
            OutlinedButton.icon(
              onPressed: _uploading ? null : _pickFile,
              icon: const Icon(Icons.video_file_outlined),
              label: const Text('파일 선택'),
            ),
            const SizedBox(width: 12),
            Expanded(child: Text(file?.name ?? '선택한 파일이 없습니다.')),
          ],
        ),
        if (_fileError != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_fileError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
        const SizedBox(height: 16),
        TextField(
          controller: _recording,
          enabled: !_uploading,
          decoration: InputDecoration(
            labelText: '녹화 시작 시각 (선택)',
            helperText: '영상 첫 장면의 실제 날짜·시각(한국 시간). 모르면 비워 두세요. 예: 2026-09-17 00:00:00',
            errorText: _recordingError,
          ),
        ),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: file == null || _uploading ? null : _upload,
          child: const Text('업로드'),
        ),
        if (_uploading) ...[
          const SizedBox(height: 16),
          LinearProgressIndicator(value: progress),
          const SizedBox(height: 4),
          Text(progress == null ? '업로드를 준비하고 있습니다.' : '${(progress * 100).floor()}%'),
        ],
      ],
    );
  }
}
