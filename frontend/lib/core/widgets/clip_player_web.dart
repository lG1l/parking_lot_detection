import 'dart:js_interop';

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

Widget buildClipVideo({required String url, VoidCallback? onUrlExpired}) =>
    _ClipVideo(url: url, onUrlExpired: onUrlExpired);

class _ClipVideo extends StatefulWidget {
  const _ClipVideo({required this.url, this.onUrlExpired});

  final String url;
  final VoidCallback? onUrlExpired;

  @override
  State<_ClipVideo> createState() => _ClipVideoState();
}

class _ClipVideoState extends State<_ClipVideo> {
  web.HTMLVideoElement? _video;
  double? _resumeAt;

  void _setup(Object element) {
    final video = element as web.HTMLVideoElement;
    _video = video;
    video
      ..controls = true
      ..preload = 'metadata'
      ..disablePictureInPicture = true
      ..style.width = '100%'
      ..style.height = '100%'
      ..style.objectFit = 'contain' // 비율을 지키고 남는 곳은 검은 여백 (07장 2.7)
      ..style.backgroundColor = 'black';
    // 브라우저 기본 메뉴의 저장 항목을 숨긴다 (07장 3.4)
    video.setAttribute('controlslist', 'nodownload noplaybackrate');
    video.addEventListener(
      'contextmenu',
      (web.Event e) {
        e.preventDefault();
      }.toJS,
    );
    video.addEventListener(
      'loadedmetadata',
      (web.Event _) {
        final at = _resumeAt;
        if (at != null) {
          _resumeAt = null;
          video.currentTime = at;
          video.play();
        }
      }.toJS,
    );
    // S3 403(만료)이면 media error가 난다. 상태 코드는 볼 수 없으므로 조회 API를 다시 부른다 (D-41)
    video.addEventListener(
      'error',
      (web.Event _) {
        widget.onUrlExpired?.call();
      }.toJS,
    );
    video.src = widget.url;
  }

  @override
  void didUpdateWidget(_ClipVideo old) {
    super.didUpdateWidget(old);
    final video = _video;
    if (video != null && old.url != widget.url) {
      // 새 URL로 끊긴 위치부터 이어 재생한다 (07장 3.2)
      final at = video.currentTime;
      _resumeAt = at > 0 ? at : null;
      video.src = widget.url;
    }
  }

  @override
  Widget build(BuildContext context) {
    return HtmlElementView.fromTagName(tagName: 'video', onElementCreated: _setup);
  }
}
