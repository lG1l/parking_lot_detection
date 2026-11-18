import 'package:flutter/material.dart';

import '../../app/theme.dart';

/// 관리자가 직접 입력해야 하는 서약 문장 (D-309).
const supervisionPledge = '본인은 비식별화 누락 부분을 가려 노출을 막고 피해자의 촬영과 유포를 통제할 것을 서약합니다';

/// 관리·감독 안내창 (07장 2.7, D-204, D-216, D-309). 후보 확인·완료·결과 화면에 들어갈 때마다 띄운다.
/// 서약 문장을 그대로 입력해야 [동의하고 열람]이 켜진다. 동의하면 true, [취소]면 false.
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
  String _typed = '';

  /// 앞뒤 공백과 띄어쓰기 개수 차이는 봐준다. 글자는 서약 문장과 같아야 한다.
  bool get _matched => _normalize(_typed) == _normalize(supervisionPledge);

  static String _normalize(String s) => s.trim().replaceAll(RegExp(r'\s+'), ' ');

  @override
  Widget build(BuildContext context) {
    const body = TextStyle(fontSize: 15, height: 1.6);
    const lines = [
      '피해자가 함께 있는 자리에서 화면을 열고 클립을 확인해 주세요.',
      '[찾음]은 피해자와 함께 장면을 확인하고 합의한 뒤에 눌러 주세요.',
      '가려지지 않은 얼굴이나 번호판이 보이면, 그 부분을 가린 채로 보여 주세요.',
    ];
    // 캔버스 새 컨셉: 둥근 큰 창, 얇은 제목 + 굵은 "함께 열람", 줄은 hair 선, 알약 버튼 (D-305)
    return AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      contentPadding: const EdgeInsets.fromLTRB(40, 32, 40, 8),
      actionsPadding: const EdgeInsets.fromLTRB(40, 8, 40, 32),
      content: ConstrainedBox(
        // 서약 문장(16px 굵게)이 한 줄에 들어가는 너비. 화면이 좁으면 줄바꿈된다.
        constraints: const BoxConstraints(maxWidth: 700),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text.rich(
                TextSpan(
                  style: TextStyle(fontSize: 28, fontWeight: FontWeight.w300, color: inkColor, height: 1.25),
                  children: [
                    TextSpan(text: '피해자와 '),
                    TextSpan(text: '함께 열람', style: TextStyle(fontWeight: FontWeight.w800)),
                    TextSpan(text: '하고, 함께 고정합니다'),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              const Text('후보 클립과 결과는 주차장 관리자의 관리·감독 아래에서 피해자와 함께 확인하는 화면입니다.', style: body),
              const SizedBox(height: 12),
              for (final line in lines)
                Container(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: const BoxDecoration(
                    border: Border(bottom: BorderSide(color: lineColor)),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('·  ', style: body),
                      Expanded(child: Text(line, style: body)),
                    ],
                  ),
                ),
              const SizedBox(height: 20),
              const Text('아래 문장을 그대로 입력해야 열 수 있습니다.', style: TextStyle(fontSize: 14, height: 1.4)),
              const SizedBox(height: 2),
              const Text(
                supervisionPledge,
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: inkColor, height: 1.6),
              ),
              const SizedBox(height: 10),
              TextField(
                key: const Key('supervision-pledge'),
                autofocus: true,
                // 엔터는 줄바꿈이 아니라 [동의하고 열람]. 문장이 다르면 아무 일도 없이 입력칸에 남는다.
                maxLines: 1,
                textInputAction: TextInputAction.done,
                onEditingComplete: () {
                  if (_matched) Navigator.pop(context, true);
                },
                // 붙여넣기로 넘기지 않게 선택·붙여넣기 메뉴를 끈다 (D-309)
                enableInteractiveSelection: false,
                onChanged: (v) => setState(() => _typed = v),
                decoration: InputDecoration(
                  hintText: '서약 문장을 입력하세요',
                  border: const OutlineInputBorder(),
                  suffixIcon: _matched ? const Icon(Icons.check_circle, color: Colors.green) : null,
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        OutlinedButton(onPressed: () => Navigator.pop(context, false), child: const Text('취소')),
        FilledButton(
          onPressed: _matched ?() => Navigator.pop(context, true) : null,
          child: const Text('동의하고 열람'),
        ),
      ],
    );
  }
}
