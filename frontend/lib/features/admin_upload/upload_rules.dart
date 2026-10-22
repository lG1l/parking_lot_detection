import '../../core/constants.dart';

const unsupportedUploadMessage = '.mp4, .avi, .mkv, .mov인 확장자만 선택해주세요. 녹화기의 MP4·AVI 내보내기를 써 주세요.';
const uploadTooLargeMessage = '파일 용량이 5GB를 초과하였습니다';

/// 업로드 전에 파일을 막는다 (D-22, D-43). 통과하면 null, 아니면 안내 문구.
String? checkUploadFile(String name, int size) {
  if (!uploadExtensions.contains(fileExtension(name))) return unsupportedUploadMessage;
  if (size > maxUploadBytes) return uploadTooLargeMessage;
  return null;
}

final _recordingPattern = RegExp(r'^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$');

/// 녹화 시작 시각 입력(한국 시간 "YYYY-MM-DD HH:mm[:ss]")을 6번에 보낼 ISO 문자열로 바꾼다 (D-85).
/// 빈 칸이면 (null, null). 틀리면 (null, 안내 문구).
(String?, String?) parseRecordingStart(String input, DateTime now) {
  final text = input.trim();
  if (text.isEmpty) return (null, null);
  final m = _recordingPattern.firstMatch(text);
  if (m == null) return (null, '2026-09-17 00:00:00 형식으로 입력해 주세요.');
  final parts = [for (var i = 1; i <= 6; i++) int.parse(m.group(i) ?? '0')];
  final local = DateTime.utc(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]);
  // DateTime.utc는 범위를 넘는 값을 넘겨 계산하므로, 그대로인지 확인해 없는 날짜를 막는다
  if (local.year != parts[0] ||
      local.month != parts[1] ||
      local.day != parts[2] ||
      local.hour != parts[3] ||
      local.minute != parts[4] ||
      local.second != parts[5]) {
    return (null, '없는 날짜나 시각입니다.');
  }
  final utc = local.subtract(const Duration(hours: 9));
  if (utc.isAfter(now.toUtc())) return (null, '지금보다 뒤의 시각은 입력할 수 없습니다.');
  String two(int n) => n.toString().padLeft(2, '0');
  final iso =
      '${parts[0].toString().padLeft(4, '0')}-${two(parts[1])}-${two(parts[2])}'
      'T${two(parts[3])}:${two(parts[4])}:${two(parts[5])}+09:00';
  return (iso, null);
}

/// 남은 업로드 시간 = (전체 − 올린 크기) ÷ 현재 속도 (D-62). 속도를 아직 모르면 null.
Duration? remainingUploadTime(int sent, int total, Duration elapsed) {
  if (sent <= 0 || elapsed.inMilliseconds <= 0) return null;
  final bytesPerMs = sent / elapsed.inMilliseconds;
  return Duration(milliseconds: ((total - sent) / bytesPerMs).round());
}

/// S3 PUT 결과 처리 (07장 2.4 "S3 응답별 처리 요약").
enum PutOutcome { ok, rejected, forbidden, interrupted }

PutOutcome putOutcome(int status) => switch (status) {
  200 => PutOutcome.ok,
  412 || 409 => PutOutcome.rejected,
  403 => PutOutcome.forbidden,
  _ => PutOutcome.interrupted,
};
