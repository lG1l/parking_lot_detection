import 'package:flutter/material.dart';

// 색 코드는 여기 한 번만 적는다. 색상표는 와이어프레임 캔버스를 따른다 (D-190).
const pointColor = Color(0xFF2D3748); // 주요 버튼 · 사전 입력 필요 · 후보 선택 가능
const inkColor = Color(0xFF121212); // 모든 글자 · 선
const subColor = Color(0xFF4A5568); // 보조 글자 · 확인 완료
const progressColor = Color(0xFFA0AEC0); // 업로드 중 · 대기 중 · 분석 중
const lineColor = Color(0xFFE2E8F0); // 테두리 · 구분선 · 종료됨
const offWhiteColor = Color(0xFFF9F9F9); // 모든 배경 · 진한 바탕 위 글자
const pointLightColor = Color(0xFFDDEBFF); // 연한 하늘색. 내가 보낸 채팅 말풍선 바탕 (D-297). 검은 글자와 대비 15.5:1
const failColor = Color(0xFF93000A); // 분석 실패

// 화면 겉모습 "새 컨셉" (D-305). 캔버스 색은 흰 글자 대비가 모자라 같은 파랑 계열에서 더 진하게 잡았다.
const whiteColor = Color(0xFFFFFFFF); // 바탕
const pillColor = Color(0xFF3F74C6); // 주요 버튼 · 파랑 글자. 흰 글자와 4.64:1 (캔버스 #5F90D9는 3.24:1)
const dangerColor = Color(0xFFC53030); // 위험 버튼 · 입력 오류. 흰 글자와 5.47:1 (캔버스 #E53E3E는 4.13:1)
const hairColor = Color(0xFFCBD5E0); // 입력칸 밑줄 · 막힌 버튼 테두리
const focusLineColor = Color(0xFF3D8BFF); // 입력칸 포커스 · 탭 밑줄 · 단계 막대. 글자가 아닌 표시로만 (3.31:1)
const glowColorTop = Color(0x333D8BFF); // 오른쪽 위 파란 빛 번짐 (rgba(61,139,255) 0.20)
const glowColorBottom = Color(0x293D8BFF); // 왼쪽 아래 파란 빛 번짐 (0.16)

// 보조 아이콘·실패 표시 색 (상태 칩은 D-305로 점 + 글자가 됐다)
const doneChipColor = Color(0xFF64748B); // 연필 아이콘 등. 흰 바탕에서 약 4.8:1
const failChipColor = Color(0xFFB04A4A); // 분석 실패·업로드 확인 안 됨 점·글자. 채도를 낮춘 빨강, 흰 바탕에서 5.35:1

// 색상표 밖의 보조 회색. 작은 안내 글자, 입력칸 테두리, 막힌 버튼.
const noteColor = Color(0xFF555555);
// 정지 장면 위 표시 (D-190, D-237): 고른 차량 노랑, 파손 부위 주황, 바닥 점 테두리 흰색, 고른 파손 변 빨강
const vehicleColor = Color(0xFFFACC15);
const damageColor = Color(0xFFC2410C);
const floorEdgeColor = Color(0xFFFFFFFF); // 바닥 모서리 점 테두리
// 고른 변은 형광 선으로 그린다 (D-295): 파손 변은 빨간 형광, 차 앞쪽 변은 초록 형광 (D-212)
const chosenEdgeColor = Color(0xFFFF2D3D);
const frontEdgeColor = Color(0xFF22E55F);
// 바닥 네 모서리 점·연결선은 밝은 파랑에 옅은 빛 번짐, 드래그 중인 파손 부위는 빨간 네 모서리만 (D-237)
const cornerColor = Color(0xFF3D8BFF);
const damageDragColor = failChipColor;
const _fieldBorderColor = Color(0xFF8F8F8B);
const _disabledTextColor = Color(0xFFA0AEC0); // 막힌 버튼 글자 (캔버스 그대로, 막힌 것은 접근성 대비 기준 밖)

const _fontFamily = 'Pretendard';

// 모서리 둥글기: 버튼·입력칸 / 대화상자 / 카드·상태 칩
const pillRadius = 999.0; // 알약 버튼
const _dialogRadius = 12.0;
const cardRadius = 16.0;
const stillRadius = 24.0; // 정지 장면·영상 상자 (D-305)

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
    surface: whiteColor,
    onSurface: inkColor,
    onSurfaceVariant: subColor,
    surfaceContainerLowest: whiteColor,
    surfaceContainerLow: whiteColor,
    surfaceContainer: whiteColor,
    surfaceContainerHigh: whiteColor,
    surfaceContainerHighest: lineColor,
    outline: _fieldBorderColor,
    outlineVariant: lineColor,
    inverseSurface: inkColor,
    onInverseSurface: offWhiteColor,
  );
  final base = ThemeData(colorScheme: colorScheme, fontFamily: _fontFamily);

  final textTheme = _textTheme(base.textTheme.apply(bodyColor: inkColor, displayColor: inkColor));
  final pillShape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(pillRadius));
  const buttonText = TextStyle(fontSize: 15, fontWeight: FontWeight.w600, letterSpacing: 0);
  const buttonSize = Size(0, 44);
  const buttonPadding = EdgeInsets.symmetric(horizontal: 20);

  return base.copyWith(
    textTheme: textTheme,
    scaffoldBackgroundColor: whiteColor,
    dividerColor: lineColor,
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: pillShape,
        minimumSize: buttonSize,
        padding: buttonPadding,
        textStyle: buttonText,
        backgroundColor: pillColor,
        foregroundColor: whiteColor,
        disabledBackgroundColor: whiteColor,
        disabledForegroundColor: _disabledTextColor,
        disabledMouseCursor: SystemMouseCursors.forbidden,
      ).copyWith(
        side: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.disabled) ? const BorderSide(color: hairColor, width: 1.5) : null,
        ),
      ),
    ),
    // 테두리형 버튼은 투명 바탕에 1.5px 검은 선. 막히면 연한 회색 선
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: ButtonStyle(
        shape: WidgetStatePropertyAll(pillShape),
        minimumSize: const WidgetStatePropertyAll(buttonSize),
        padding: const WidgetStatePropertyAll(buttonPadding),
        textStyle: const WidgetStatePropertyAll(buttonText),
        foregroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.disabled) ? _disabledTextColor : inkColor,
        ),
        backgroundColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.disabled) ? whiteColor : Colors.transparent,
        ),
        side: WidgetStateProperty.resolveWith(
          (s) => BorderSide(color: s.contains(WidgetState.disabled) ? hairColor : inkColor, width: 1.5),
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        shape: pillShape,
        minimumSize: buttonSize,
        textStyle: buttonText,
        foregroundColor: pillColor,
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
    // 입력칸은 밑줄만 (D-305). 칸 이름은 위 작은 소제목이라 라벨은 화면이 따로 둔다
    inputDecorationTheme: const InputDecorationTheme(
      filled: false,
      contentPadding: EdgeInsets.symmetric(vertical: 12),
      border: UnderlineInputBorder(borderSide: BorderSide(color: hairColor, width: 1.5)),
      enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: hairColor, width: 1.5)),
      focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: focusLineColor, width: 2)),
      errorBorder: UnderlineInputBorder(borderSide: BorderSide(color: dangerColor, width: 1.5)),
      focusedErrorBorder: UnderlineInputBorder(borderSide: BorderSide(color: dangerColor, width: 2)),
      errorStyle: TextStyle(color: dangerColor),
    ),
    // 탭은 파란 밑줄 2px (D-305)
    tabBarTheme: const TabBarThemeData(
      indicatorColor: focusLineColor,
      indicatorSize: TabBarIndicatorSize.label,
      dividerColor: lineColor,
      labelColor: inkColor,
      unselectedLabelColor: subColor,
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(cardRadius)),
      side: BorderSide.none,
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: whiteColor,
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
