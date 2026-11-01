import 'dart:ui' show Size;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config.dart';
import 'browser_stub.dart' if (dart.library.js_interop) 'browser_web.dart';

/// 브라우저가 고른 로컬 파일. 바이트를 메모리에 올리지 않고 파일 객체를 그대로 쥔다 (07장 2.4).
abstract class PickedFile {
  String get name;
  int get size;

  /// 미리보기용 로컬 주소 (사진 미리보기, D-92).
  String get objectUrl;
}

/// 웹 전용 기능. 테스트(VM)에서는 [browserProvider]를 가짜로 바꿔 끼운다.
abstract class Browser {
  /// 파일 고르기 창을 띄운다. 취소하면 null.
  Future<PickedFile?> pickFile(List<String> extensions);

  /// [url]에 파일 바이트를 그대로 PUT한다. 돌려주는 값은 HTTP 상태 번호이고,
  /// 네트워크 오류면 0이다. 진행률은 XMLHttpRequest의 progress 이벤트다 (07장 2.4).
  Future<int> putFile(
    String url,
    PickedFile file, {
    Map<String, String> headers = const {},
    void Function(int sent, int total)? onProgress,
  });

  /// 이미지의 원본 픽셀 크기(naturalWidth·naturalHeight). 못 읽으면 null (05장 5.6).
  Future<Size?> imageNaturalSize(String url);

  /// 개발 중 확인용 콘솔 출력 (07장 2.4 403 처리).
  void log(String message);

  /// 앱 안에 이전 기록이 있으면 브라우저 뒤로 가기를 하고 true. 없으면 false (D-185).
  bool historyBack();
}

// 백엔드 연결 필요: 데모에서는 S3에 올리지 않고 진행률만 흉내 낸다
final browserProvider = Provider<Browser>(
  (ref) => useBackend ? createBrowser() : DemoBrowser(createBrowser()),
);

/// 파일 고르기·이미지 크기는 진짜 브라우저로 하고, 업로드(PUT)만 흉내 낸다.
class DemoBrowser implements Browser {
  DemoBrowser(this._real);

  final Browser _real;

  @override
  Future<PickedFile?> pickFile(List<String> extensions) => _real.pickFile(extensions);

  @override
  Future<int> putFile(
    String url,
    PickedFile file, {
    Map<String, String> headers = const {},
    void Function(int sent, int total)? onProgress,
  }) async {
    for (var i = 1; i <= 10; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 150));
      onProgress?.call(file.size * i ~/ 10, file.size);
    }
    return 200;
  }

  @override
  Future<Size?> imageNaturalSize(String url) => _real.imageNaturalSize(url);

  @override
  void log(String message) => _real.log(message);

  @override
  bool historyBack() => _real.historyBack();
}
