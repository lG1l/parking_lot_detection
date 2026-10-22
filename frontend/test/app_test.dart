import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/main.dart';

void main() {
  testWidgets('첫 화면은 영상 목록이다', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: App()));
    await tester.pumpAndSettle();
    expect(find.textContaining('영상 목록'), findsWidgets);
  });
}
