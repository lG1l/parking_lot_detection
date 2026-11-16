import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/app/theme.dart';
import 'package:parking_lot_frontend/core/widgets/common.dart';

void main() {
  test('상태 글자마다 07장 2.2의 점 색을 고르고, 모르는 글자는 예외 없이 회색이다 (D-305)', () {
    expect(statusDotStyle('업로드 중').dot, progressColor);
    expect(statusDotStyle('대기 중').dot, progressColor);
    expect(statusDotStyle('분석 중').dot, progressColor);
    expect(statusDotStyle('업로드 필요').dot, progressColor);
    expect(statusDotStyle('사전 입력 필요').dot, pointColor);
    expect(statusDotStyle('확인 완료').dot, pointColor);
    expect(statusDotStyle('후보 선택 가능').dot, focusLineColor);
    expect(statusDotStyle('분석 실패').dot, failChipColor);
    expect(statusDotStyle('업로드 확인 안 됨').dot, failChipColor);
    expect(statusDotStyle('수락 대기 중').dot, isNull); // 속이 빈 테두리
    expect(statusDotStyle('종료됨').dot, isNull);
    expect(statusDotStyle('분석 완료').dot, inkColor);
    expect(statusDotStyle('처음 보는 상태').dot, progressColor);
  });
}
