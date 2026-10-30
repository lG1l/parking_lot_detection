// 화면에 보이는 시각·시간 형식 (07장 3.3, 2.9).

const _kstOffset = Duration(hours: 9);

String _two(int n) => n.toString().padLeft(2, '0');

/// 시간대가 붙은 ISO 8601 문자열을 브라우저 시간대와 상관없이 한국 시간으로 바꾼다.
/// 돌려주는 DateTime의 필드(year, hour 등)가 한국 시간 값이다.
DateTime toKst(String iso) => DateTime.parse(iso).toUtc().add(_kstOffset);

/// "YYYY-MM-DD" (한국 시간).
String formatKstDate(String iso) {
  final t = toKst(iso);
  return '${t.year}-${_two(t.month)}-${_two(t.day)}';
}

/// "YYYY-MM-DD HH:mm" (한국 시간).
String formatKstMinute(String iso) {
  final t = toKst(iso);
  return '${t.year}-${_two(t.month)}-${_two(t.day)} ${_two(t.hour)}:${_two(t.minute)}';
}

/// "YYYY-MM-DD HH:mm:ss" (한국 시간).
String formatKstSecond(String iso) {
  final t = toKst(iso);
  return '${t.year}-${_two(t.month)}-${_two(t.day)} '
      '${_two(t.hour)}:${_two(t.minute)}:${_two(t.second)}';
}

/// "HH:mm:ss" (한국 시간).
String formatKstTime(String iso) {
  final t = toKst(iso);
  return '${_two(t.hour)}:${_two(t.minute)}:${_two(t.second)}';
}

/// 원본 영상 기준 초를 "HH:MM:SS"로. 초 미만은 버린다 (07장 2.9).
String formatElapsed(double sec) {
  final total = sec.floor();
  final h = total ~/ 3600;
  final m = (total % 3600) ~/ 60;
  final s = total % 60;
  return '${_two(h)}:${_two(m)}:${_two(s)}';
}

/// 열람기한 문구 (07장 3.3). `null`이면 업로드 완료 전 안내.
String viewExpiresText(String? viewExpiresAt) {
  if (viewExpiresAt == null) return '업로드 완료 후 열람기한이 정해집니다';
  return '${formatKstMinute(viewExpiresAt)}까지 열람 가능';
}

/// 결과·후보 화면 위의 기한 문구 (07장 2.7, 2.9).
String resultExpiresText(String? viewExpiresAt) {
  if (viewExpiresAt == null) return '업로드 완료 후 열람기한이 정해집니다';
  return '이 결과는 ${formatKstMinute(viewExpiresAt)}까지 열람 가능합니다.';
}
