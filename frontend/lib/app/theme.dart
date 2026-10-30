import 'package:flutter/material.dart';

// 색 코드는 여기 한 번만 적는다. 색상표는 와이어프레임 캔버스를 따른다 (D-190).
const pointColor = Color(0xFF2D3748); // 주요 버튼 · 사전 입력 필요 · 후보 선택 가능
const inkColor = Color(0xFF121212); // 모든 글자 · 선
const subColor = Color(0xFF4A5568); // 보조 글자 · 확인 완료
const progressColor = Color(0xFFA0AEC0); // 업로드 중 · 대기 중 · 분석 중
const lineColor = Color(0xFFE2E8F0); // 테두리 · 구분선 · 종료됨
const offWhiteColor = Color(0xFFF9F9F9); // 모든 배경 · 진한 바탕 위 글자
const failColor = Color(0xFF93000A); // 분석 실패

// 목록 상태 칩 바탕. 색상표보다 조금 연하게 (D-190, 팀원 1)
const progressChipColor = Color(0xFFB8C2D0); // 업로드 중·대기 중·분석 중. 검정 글자와 약 10:1
const doneChipColor = Color(0xFF64748B); // 확인 완료. 흰 글자와 약 4.5:1
const failChipColor = Color(0xFFB04A4A); // 분석 실패·업로드 확인 안 됨. 채도를 낮춘 빨강, 흰 글자와 약 5.1:1

// 색상표 밖의 보조 회색. 작은 안내 글자, 입력칸 테두리, 막힌 버튼.
const noteColor = Color(0xFF555555);
// 정지 장면 위 표시 (D-190): 고른 차량 노랑, 파손 부위 주황, 바닥 변 흰색, 고른 파손 변 빨강
const vehicleColor = Color(0xFFFACC15);
const damageColor = Color(0xFFC2410C);
const floorEdgeColor = Color(0xFFFFFFFF);
const chosenEdgeColor = Color(0xFFDC2626);
const _fieldBorderColor = Color(0xFF8F8F8B);
const _disabledBorderColor = Color(0xFFB5B5B5);
const _disabledTextColor = Color(0xFF767676);
const _disabledFillColor = Color(0xFFEFEFED);

const _fontFamily = 'Pretendard';

// 모서리 둥글기: 버튼·입력칸 / 대화상자 / 카드·상태 칩
const _smallRadius = 6.0;
const _dialogRadius = 12.0;
const cardRadius = 16.0;

/// 카드 아래 옅은 그림자 (캔버스 `box-shadow`).
const cardShadow = [
  BoxShadow(color: Color(0x0F2D3748), offset: Offset(0, 1), blurRadius: 3),
  BoxShadow(color: Color(0x0A2D3748), offset: Offset(0, 1), blurRadius: 2),
];

/// 앱 전체 겉모습을 정하는 곳. 화면은 색을 역할 이름(colorScheme.xxx)이나 위 상수로만 쓴다.
final appTheme = _buildTheme();

ThemeData _buildTheme() {
  final colorScheme = ColorScheme.fromSeed(
    seedColor: pointColor,
    dynamicSchemeVariant: DynamicSchemeVariant.fidelity,
    primary: pointColor,
    onPrimary: offWhiteColor,
    secondary: subColor,
    onSecondary: offWhiteColor,
    tertiary: pointColor,
    onTertiary: offWhiteColor,
    error: failColor,
    onError: offWhiteColor,
    surface: offWhiteColor,
    onSurface: inkColor,
    onSurfaceVariant: subColor,
    surfaceContainerLowest: offWhiteColor,
    surfaceContainerLow: offWhiteColor,
    surfaceContainer: offWhiteColor,
    surfaceContainerHigh: offWhiteColor,
    surfaceContainerHighest: lineColor,
    outline: _fieldBorderColor,
    outlineVariant: lineColor,
    inverseSurface: inkColor,
    onInverseSurface: offWhiteColor,
  );
  final base = ThemeData(colorScheme: colorScheme, fontFamily: _fontFamily);

  final textTheme = _textTheme(base.textTheme.apply(bodyColor: inkColor, displayColor: inkColor));
  final smallShape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(_smallRadius));
  const buttonText = TextStyle(fontSize: 15, fontWeight: FontWeight.w600, letterSpacing: 0);
  const buttonSize = Size(0, 44);
  const buttonPadding = EdgeInsets.symmetric(horizontal: 20);

  return base.copyWith(
    textTheme: textTheme,
    scaffoldBackgroundColor: offWhiteColor,
    dividerColor: lineColor,
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: smallShape,
        minimumSize: buttonSize,
        padding: buttonPadding,
        textStyle: buttonText,
        backgroundColor: pointColor,
        foregroundColor: offWhiteColor,
        disabledBackgroundColor: _disabledFillColor,
        disabledForegroundColor: _disabledTextColor,
      ),
    ),
    // 테두리형 버튼은 1.5px 검은 선. 막히면 연한 회색 선과 바탕
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: ButtonStyle(
        shape: WidgetStatePropertyAll(smallShape),
        minimumSize: const WidgetStatePropertyAll(buttonSize),
        padding: const WidgetStatePropertyAll(buttonPadding),
        textStyle: const WidgetStatePropertyAll(buttonText),
        foregroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.disabled) ? _disabledTextColor : inkColor,
        ),
        backgroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.disabled) ? _disabledFillColor : offWhiteColor,
        ),
        side: WidgetStateProperty.resolveWith(
          (s) => BorderSide(color: s.contains(WidgetState.disabled) ? _disabledBorderColor : inkColor, width: 1.5),
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        shape: smallShape,
        minimumSize: buttonSize,
        textStyle: buttonText,
        foregroundColor: pointColor,
      ),
    ),
    cardTheme: CardThemeData(
      color: offWhiteColor,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(cardRadius),
        side: const BorderSide(color: lineColor),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: offWhiteColor,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(_smallRadius),
        borderSide: const BorderSide(color: _fieldBorderColor, width: 1.5),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(_smallRadius),
        borderSide: const BorderSide(color: _fieldBorderColor, width: 1.5),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(_smallRadius),
        borderSide: const BorderSide(color: pointColor, width: 2),
      ),
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(cardRadius)),
      side: BorderSide.none,
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: offWhiteColor,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(_dialogRadius),
        side: const BorderSide(color: inkColor, width: 1.5),
      ),
      titleTextStyle: textTheme.titleMedium?.copyWith(fontSize: 18),
      contentTextStyle: textTheme.bodyLarge?.copyWith(fontSize: 15, height: 1.6),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: pointColor,
      circularTrackColor: lineColor,
      linearTrackColor: lineColor,
    ),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.selected) ? pointColor : null),
      checkColor: const WidgetStatePropertyAll(offWhiteColor),
    ),
    snackBarTheme: const SnackBarThemeData(backgroundColor: inkColor),
  );
}

/// 크기는 Material 3 기본 그대로. 굵기만 정하고 자간은 0으로 둔다
/// (기본 자간은 영문 기준이라 한글이 벌어져 보인다).
TextTheme _textTheme(TextTheme t) {
  TextStyle? w(TextStyle? s, FontWeight weight) => s?.copyWith(fontWeight: weight, letterSpacing: 0);
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
    bodySmall: w(t.bodySmall, FontWeight.w400)?.copyWith(color: noteColor, fontSize: 13),
    labelLarge: w(t.labelLarge, FontWeight.w500),
    labelMedium: w(t.labelMedium, FontWeight.w500),
    labelSmall: w(t.labelSmall, FontWeight.w500),
  );
}
