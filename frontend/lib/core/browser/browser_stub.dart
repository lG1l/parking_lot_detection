import 'dart:ui' show Size;

import 'browser.dart';

/// 웹이 아닌 곳(테스트 VM)에서 쓰는 빈 구현. 테스트는 가짜로 바꿔 끼운다.
Browser createBrowser() => _UnsupportedBrowser();

class _UnsupportedBrowser implements Browser {
  @override
  Future<PickedFile?> pickFile(List<String> extensions) async => null;

  @override
  Future<int> putFile(
    String url,
    PickedFile file, {
    Map<String, String> headers = const {},
    void Function(int sent, int total)? onProgress,
  }) async => 0;

  @override
  Future<Size?> imageNaturalSize(String url) async => null;

  @override
  void log(String message) {}

  @override
  bool historyBack() => false;
}
