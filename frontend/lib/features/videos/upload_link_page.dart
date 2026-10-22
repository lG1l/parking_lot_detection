import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api/api.dart';
import '../../core/config.dart';
import '../../core/format.dart';
import '../../core/widgets/common.dart';

/// 관리자에게 줄 링크 주소. 지금 열린 주소 앞부분에 `#/upload/{token}`을 붙인다 (D-12).
String uploadLinkFor(Uri base, String token) =>
    '${base.removeFragment().replace(query: '')}#/upload/$token'.replaceFirst('?#', '#');

/// 2.3 업로드 링크 발급. 4번은 버튼을 눌렀을 때만 부른다.
/// 화면을 열 때 부르면 이미 관리자에게 보낸 링크가 무효가 된다 (05장 5.4).
class UploadLinkPage extends ConsumerStatefulWidget {
  const UploadLinkPage({super.key});

  @override
  ConsumerState<UploadLinkPage> createState() => _UploadLinkPageState();
}

class _UploadLinkPageState extends ConsumerState<UploadLinkPage> {
  String? _link;
  String? _token;
  String? _expiresAt;
  bool _busy = false;

  Future<void> _issue() async {
    setState(() => _busy = true);
    // 백엔드 연결 필요: 4번 업로드 링크 발급
    await backendNotice(context, ref, '링크 발급');
    try {
      final r = await ref.read(apiProvider).issueUploadLink();
      if (mounted) {
        setState(() {
          _token = r.token;
          _link = uploadLinkFor(Uri.base, r.token);
          _expiresAt = r.expiresAt;
        });
      }
    } catch (e) {
      if (mounted) handleCommonError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: _link!));
    if (mounted) showMessage(context, '링크 주소를 복사했습니다.');
  }

  @override
  Widget build(BuildContext context) {
    final link = _link;
    return PageFrame(
      title: '업로드 링크 발급',
      actions: const [BackToListButton()],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Notice('이 링크는 주차장 관리자에게 보여주는 용도입니다.'),
          const SizedBox(height: 16),
          if (link == null)
            FilledButton(
              onPressed: _busy ? null : _issue,
              child: const Text('링크 발급'),
            )
          else ...[
            SelectableText(link, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text('링크는 ${formatKstMinute(_expiresAt!)}까지 한 번만 쓸 수 있습니다.'),
            const SizedBox(height: 16),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                FilledButton.icon(
                  onPressed: _copy,
                  icon: const Icon(Icons.copy),
                  label: const Text('주소 복사'),
                ),
                OutlinedButton(
                  onPressed: _busy ? null : _issue,
                  child: const Text('링크 다시 발급'),
                ),
                const Text('다시 발급하면 이전 링크는 쓸 수 없게 됩니다.'),
              ],
            ),
            // 데모 전용: 관리자가 링크를 연 화면을 바로 본다
            if (!useBackend) ...[
              const SizedBox(height: 16),
              TextButton.icon(
                onPressed: () => context.go('/upload/$_token'),
                icon: const Icon(Icons.open_in_new),
                label: const Text('(데모) 관리자 업로드 화면 열기'),
              ),
            ],
          ],
        ],
      ),
    );
  }
}
