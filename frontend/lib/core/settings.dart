import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'browser/browser.dart';

/// 화면 글자 크기 (D-236). [scale]은 앱 전체 글자에 곱하는 배율이다.
enum TextSize {
  small('작게', 0.9),
  normal('보통', 1.0),
  large('크게', 1.15);

  const TextSize(this.label, this.scale);

  final String label;
  final double scale;
}

/// 브라우저 localStorage에 글자 크기 이름을 저장하는 키.
const textSizeStorageKey = 'text_size';

/// 지금 고른 글자 크기. 처음에는 브라우저에 저장된 값을 읽고(없거나 알 수 없으면 보통),
/// 바꾸면 상태를 바꾸고 브라우저에 저장한다. 서버는 부르지 않는다.
final textSizeProvider = NotifierProvider<TextSizeNotifier, TextSize>(TextSizeNotifier.new);

class TextSizeNotifier extends Notifier<TextSize> {
  @override
  TextSize build() {
    final saved = ref.read(browserProvider).readLocal(textSizeStorageKey);
    return TextSize.values.firstWhere((s) => s.name == saved, orElse: () => TextSize.normal);
  }

  void select(TextSize size) {
    state = size;
    ref.read(browserProvider).writeLocal(textSizeStorageKey, size.name);
  }
}
