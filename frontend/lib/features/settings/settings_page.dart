import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/settings.dart';
import '../../core/widgets/common.dart';

/// 2.14 환경설정 (두 계정). 글자 크기를 고르면 [저장] 없이 바로 앱 전체에 적용되고
/// 브라우저에 저장된다 (D-236). 서버는 부르지 않는다.
class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final size = ref.watch(textSizeProvider);
    return PageFrame(
      current: NavItem.settings,
      title: '환경설정',
      maxWidth: 640,
      child: PageCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SmallText('글자 크기'),
            const SizedBox(height: 12),
            SegmentedButton<TextSize>(
              showSelectedIcon: false,
              segments: [for (final s in TextSize.values) ButtonSegment(value: s, label: Text(s.label))],
              selected: {size},
              onSelectionChanged: (picked) => ref.read(textSizeProvider.notifier).select(picked.first),
            ),
          ],
        ),
      ),
    );
  }
}
