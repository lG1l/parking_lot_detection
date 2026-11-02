import 'package:flutter/material.dart';

import '../../app/theme.dart';

/// 관리·감독 안내창 (07장 2.7, D-204, D-216). 후보 확인·완료·결과 화면에 들어갈 때마다 띄운다.
/// 체크해야 [동의하고 열람]이 켜진다. 동의하면 true, [취소]면 false.
Future<bool> askSupervision(BuildContext context) async {
  final ok = await showDialog<bool>(
    context: context,
    barrierDismissible: false,
    builder: (_) => const _SupervisionDialog(),
  );
  return ok ?? false;
}

class _SupervisionDialog extends StatefulWidget {
  const _SupervisionDialog();

  @override
  State<_SupervisionDialog> createState() => _SupervisionDialogState();
}

class _SupervisionDialogState extends State<_SupervisionDialog> {
  bool _checked = false;

  @override
  Widget build(BuildContext context) {
    const body = TextStyle(fontSize: 15, height: 1.6);
    return AlertDialog(
      title: const Text('피해자와 함께 열람하고, 함께 고정합니다'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('후보 클립과 결과는 주차장 관리자의 관리·감독 아래에서 피해자와 함께 확인하는 화면입니다.', style: body),
            const SizedBox(height: 12),
            for (final line in const [
              '피해자가 함께 있는 자리에서 화면을 열어 주세요.',
              '후보 클립은 피해자와 함께 보면서 확인해 주세요.',
              '[고정]은 피해자와 함께 장면을 확인하고 합의한 뒤에 눌러 주세요.',
              '가려지지 않은 얼굴이나 번호판이 보이면, 그 부분을 가린 채로 보여 주세요.',
            ])
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('·  ', style: body),
                    Expanded(child: Text(line, style: body)),
                  ],
                ),
              ),
            const SizedBox(height: 12),
            CheckboxListTile(
              value: _checked,
              onChanged: (v) => setState(() => _checked = v ?? false),
              title: const Text(
                '관리자로서 피해자와 함께 열람하고, 고정할 장면도 피해자와 함께 확인하겠습니다.',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: inkColor),
              ),
              controlAffinity: ListTileControlAffinity.leading,
              contentPadding: EdgeInsets.zero,
            ),
          ],
        ),
      ),
      actions: [
        OutlinedButton(onPressed: () => Navigator.pop(context, false), child: const Text('취소')),
        FilledButton(
          onPressed: _checked ? () => Navigator.pop(context, true) : null,
          child: const Text('동의하고 열람'),
        ),
      ],
    );
  }
}
