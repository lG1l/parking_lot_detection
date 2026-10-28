import 'package:flutter/material.dart';

// 색 코드는 여기 한 번만 적는다(D-183).
const _grayAccent = Color(0xFF6E767B); // 강조색. 흰 글자와 명암비 4.63:1
const _pointColor = Color(0xFF45586B); // 영상 목록 "할 일" 칩
const _blackColor = Color(0xFF121212); // 스낵바 바탕

// 영상 목록 칩 전용 색. ColorScheme에 맞는 자리가 없어 이름으로 내보낸다 (D-185).
const reviewChipColor = Color(0xFF2E6B5E); // "확인 가능" 청록. 흰 글자와 6.2:1
const doneChipColor = Color(0xFF5B4B8A); // "확인 끝남" 보라회색. 흰 글자와 7.5:1

const _fontFamily = 'Pretendard';

// 모서리 둥글기: 버튼·입력칸·칩 / 카드·대화상자
const _smallRadius = 8.0;
const _largeRadius = 12.0;

/// 앱 전체 겉모습을 정하는 곳. 화면은 색을 역할 이름(colorScheme.xxx)으로만 쓴다.
final appTheme = _buildTheme();

ThemeData _buildTheme() {
  final colorScheme = ColorScheme.fromSeed(
    seedColor: _grayAccent,
    // 기본 방식(tonalSpot)은 채도를 올려 청회색이 되므로, 시드 색을 그대로 살린다.
    dynamicSchemeVariant: DynamicSchemeVariant.fidelity,
    primary: _grayAccent,
    onPrimary: Colors.white,
    tertiary: _pointColor,
    onTertiary: Colors.white,
    inverseSurface: _blackColor,
  );
  final base = ThemeData(colorScheme: colorScheme, fontFamily: _fontFamily);

  final textTheme = _textTheme(base.textTheme);
  final smallShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(_smallRadius),
  );

  return base.copyWith(
    textTheme: textTheme,
    scaffoldBackgroundColor: colorScheme.surfaceContainerLow,
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(shape: smallShape),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(shape: smallShape),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(shape: smallShape),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_largeRadius),
        side: BorderSide(color: colorScheme.outlineVariant),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(_smallRadius),
      ),
    ),
    chipTheme: ChipThemeData(shape: smallShape),
    dialogTheme: DialogThemeData(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_largeRadius),
      ),
    ),
    // 상단 바는 화면 배경과 한 면으로 보이게 같은 색, 선 없음 (D-184)
    appBarTheme: AppBarTheme(
      backgroundColor: colorScheme.surfaceContainerLow,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: textTheme.titleLarge?.copyWith(
        color: colorScheme.onSurface,
      ),
    ),
  );
}

/// 크기는 Material 3 기본 그대로. 굵기만 정하고 자간은 0으로 둔다
/// (기본 자간은 영문 기준이라 한글이 벌어져 보인다).
TextTheme _textTheme(TextTheme t) {
  TextStyle? w(TextStyle? s, FontWeight weight) =>
      s?.copyWith(fontWeight: weight, letterSpacing: 0);
  return t.copyWith(
    displayLarge: w(t.displayLarge, FontWeight.w400),
    displayMedium: w(t.displayMedium, FontWeight.w400),
    displaySmall: w(t.displaySmall, FontWeight.w400),
    headlineLarge: w(t.headlineLarge, FontWeight.w600),
    headlineMedium: w(t.headlineMedium, FontWeight.w600),
    headlineSmall: w(t.headlineSmall, FontWeight.w600),
    titleLarge: w(t.titleLarge, FontWeight.w600),
    titleMedium: w(t.titleMedium, FontWeight.w600),
    titleSmall: w(t.titleSmall, FontWeight.w600),
    bodyLarge: w(t.bodyLarge, FontWeight.w400),
    bodyMedium: w(t.bodyMedium, FontWeight.w400),
    bodySmall: w(t.bodySmall, FontWeight.w400),
    labelLarge: w(t.labelLarge, FontWeight.w500),
    labelMedium: w(t.labelMedium, FontWeight.w500),
    labelSmall: w(t.labelSmall, FontWeight.w500),
  );
}
