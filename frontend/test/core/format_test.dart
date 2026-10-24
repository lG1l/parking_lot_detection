import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/format.dart';

void main() {
  test('열람기한은 브라우저 시간대와 상관없이 한국 시간으로 보인다 (07장 3.3)', () {
    expect(viewExpiresText('2026-10-19T10:00:00+09:00'), '2026-10-19 10:00까지 열람 가능');
    expect(viewExpiresText('2026-10-19T01:30:00Z'), '2026-10-19 10:30까지 열람 가능');
    expect(viewExpiresText(null), '업로드 완료 후 열람기한이 정해집니다');
  });

  test('원본 기준 초는 시:분:초, 초 미만은 버린다 (07장 2.9)', () {
    expect(formatElapsed(13235.9), '03:40:35');
    expect(formatElapsed(0), '00:00:00');
    expect(formatElapsed(86399), '23:59:59');
  });
}
