import 'dart:async';
import 'dart:js_interop';
import 'dart:ui' show Size;

import 'package:web/web.dart' as web;

import 'browser.dart';

Browser createBrowser() => _WebBrowser();

class _WebFile implements PickedFile {
  _WebFile(this.file);

  final web.File file;
  String? _objectUrl;

  @override
  String get name => file.name;

  @override
  int get size => file.size;

  @override
  String get objectUrl => _objectUrl ??= web.URL.createObjectURL(file);
}

class _WebBrowser implements Browser {
  @override
  Future<PickedFile?> pickFile(List<String> extensions) {
    final input = web.HTMLInputElement()
      ..type = 'file'
      ..accept = extensions.map((e) => '.$e').join(',');
    final done = Completer<PickedFile?>();
    input.onchange = (web.Event _) {
      final f = input.files?.item(0);
      if (!done.isCompleted) done.complete(f == null ? null : _WebFile(f));
    }.toJS;
    input.addEventListener(
      'cancel',
      (web.Event _) {
        if (!done.isCompleted) done.complete(null);
      }.toJS,
    );
    input.click();
    return done.future;
  }

  @override
  Future<int> putFile(
    String url,
    PickedFile file, {
    Map<String, String> headers = const {},
    void Function(int sent, int total)? onProgress,
  }) {
    final done = Completer<int>();
    final xhr = web.XMLHttpRequest()..open('PUT', url);
    headers.forEach((name, value) => xhr.setRequestHeader(name, value));
    if (onProgress != null) {
      xhr.upload.onprogress = (web.ProgressEvent e) {
        onProgress(e.loaded, e.total);
      }.toJS;
    }
    void finish(int status) {
      if (!done.isCompleted) done.complete(status);
    }

    xhr.onload = (web.Event _) {
      finish(xhr.status);
    }.toJS;
    xhr.onerror = (web.Event _) {
      finish(0);
    }.toJS;
    xhr.onabort = (web.Event _) {
      finish(0);
    }.toJS;
    xhr.send((file as _WebFile).file);
    return done.future;
  }

  @override
  Future<Size?> imageNaturalSize(String url) {
    final done = Completer<Size?>();
    final img = web.HTMLImageElement();
    img.onload = (web.Event _) {
      if (!done.isCompleted) {
        done.complete(Size(img.naturalWidth.toDouble(), img.naturalHeight.toDouble()));
      }
    }.toJS;
    img.onerror = (web.Event _) {
      if (!done.isCompleted) done.complete(null);
    }.toJS;
    img.src = url;
    return done.future;
  }

  @override
  void log(String message) => web.console.log(message.toJS);
}
