import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/settings.dart';
import '../../core/widgets/common.dart';

/// 2.14 환경설정 (두 계정). 글자 크기를 고르면 [저장] 없이 바로 앱 전체에 적용되고
/// 브라우저에 저장된다 (D-236). 서버는 부르지 않는다. 모양은 캔버스(제목 · 줄마다 오른쪽 단추)를 따른다 (D-237).
class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final size = ref.watch(textSizeProvider);
    void select(TextSize? s) {
      if (s != null) ref.read(textSizeProvider.notifier).select(s);
    }

    return PageFrame(
      current: NavItem.settings,
      title: '환경설정',
      child: Align(
        alignment: Alignment.topLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: PageCard(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 8),
            child: RadioGroup<TextSize>(
              groupValue: size,
              onChanged: select,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 14, bottom: 6),
                    child: Text('글자 크기', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600)),
                  ),
                  // 캔버스처럼 제목 아래 첫 줄부터 위쪽 선을 둔다
                  for (final s in TextSize.values)
                    OptionRow(
                      label: s.label,
                      onTap: () => select(s),
                      trailing: Radio<TextSize>(value: s),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
