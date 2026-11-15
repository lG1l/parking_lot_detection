import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/app/theme.dart';

// WCAG 명암비: (밝은 쪽 + 0.05) / (어두운 쪽 + 0.05)
double _contrast(Color a, Color b) {
  final la = a.computeLuminance();
  final lb = b.computeLuminance();
  final hi = la > lb ? la : lb;
  final lo = la > lb ? lb : la;
  return (hi + 0.05) / (lo + 0.05);
}

void main() {
  test('주요 버튼과 위험 버튼의 흰 글자는 명암비 4.5:1 이상이다 (D-305)', () {
    expect(_contrast(pillColor, whiteColor), greaterThanOrEqualTo(4.5));
    expect(_contrast(dangerColor, whiteColor), greaterThanOrEqualTo(4.5));
  });
}
