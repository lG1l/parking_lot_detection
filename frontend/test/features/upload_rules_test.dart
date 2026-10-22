import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/features/admin_upload/upload_rules.dart';
import 'package:parking_lot_frontend/features/videos/upload_link_page.dart';

void main() {
  test('확장자와 5GB를 업로드 전에 막는다 (D-22, D-43)', () {
    expect(checkUploadFile('CH03.MP4', 100), isNull);
    expect(checkUploadFile('clip.wmv', 100), unsupportedUploadMessage);
    expect(checkUploadFile('noext', 100), unsupportedUploadMessage);
    expect(checkUploadFile('a.mp4', 5 * 1024 * 1024 * 1024 + 1), uploadTooLargeMessage);
  });

  group('녹화 시작 시각 (D-85)', () {
    final now = DateTime.utc(2026, 10, 22, 3); // 한국 12:00

    test('비우면 보내지 않는다', () {
      expect(parseRecordingStart('  ', now), (null, null));
    });

    test('한국 시간으로 읽어 시간대를 붙인다', () {
      expect(parseRecordingStart('2026-09-17 00:00:00', now).$1, '2026-09-17T00:00:00+09:00');
      expect(parseRecordingStart('2026-09-17 03:40', now).$1, '2026-09-17T03:40:00+09:00');
    });

    test('틀린 형식·없는 날짜·미래를 막는다', () {
      expect(parseRecordingStart('2026/09/17', now).$2, isNotNull);
      expect(parseRecordingStart('2026-02-30 00:00:00', now).$2, isNotNull);
      expect(parseRecordingStart('2026-10-22 12:00:01', now).$2, isNotNull);
    });
  });

  test('남은 시간 = (전체 − 올린 크기) ÷ 현재 속도 (D-62)', () {
    expect(remainingUploadTime(0, 100, const Duration(seconds: 1)), isNull);
    expect(remainingUploadTime(25, 100, const Duration(seconds: 10)), const Duration(seconds: 30));
  });

  test('S3 응답별 처리 (07장 2.4)', () {
    expect(putOutcome(200), PutOutcome.ok);
    expect(putOutcome(412), PutOutcome.rejected);
    expect(putOutcome(409), PutOutcome.rejected);
    expect(putOutcome(403), PutOutcome.forbidden);
    expect(putOutcome(0), PutOutcome.interrupted);
  });

  test('업로드 링크는 지금 열린 주소 앞부분에 붙인다 (D-12)', () {
    expect(
      uploadLinkFor(Uri.parse('http://3.35.1.2/#/videos/upload-link'), 'abc'),
      'http://3.35.1.2/#/upload/abc',
    );
  });
}
