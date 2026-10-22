import 'package:flutter/material.dart';

import 'clip_player_stub.dart' if (dart.library.js_interop) 'clip_player_web.dart';

/// 마스킹본 클립 재생기 (07장 2.7, 2.9).
///
/// - 브라우저 `<video>`로 스트리밍만 한다. 다운로드 메뉴와 오른쪽 클릭을 막는다 (3.4).
/// - 재생 URL이 만료돼 불러오지 못하면 [onUrlExpired]를 부른다. 화면은 조회 API를 다시 불러
///   새 [url]을 넘기고, 플레이어는 끊긴 위치부터 이어 재생한다 (3.2, D-41).
/// - 키보드: 포커스가 있으면 Space 재생/일시정지, ←/→ 5초 이동은 브라우저 기본 동작이다 (3.5).
class ClipPlayer extends StatelessWidget {
  const ClipPlayer({super.key, required this.url, this.onUrlExpired});

  final String url;
  final VoidCallback? onUrlExpired;

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 16 / 9, // 보여줄 크롭은 16:9 고정 (D-175)
      child: ColoredBox(
        color: Colors.black,
        // 백엔드 연결 필요: 데모 데이터에는 영상 파일이 없어 주소가 비어 있다
        child: url.isEmpty
            ? const Center(
                child: Text('예시 영상이 없습니다 (백엔드 연결 필요)', style: TextStyle(color: Colors.white70)),
              )
            : buildClipVideo(url: url, onUrlExpired: onUrlExpired),
      ),
    );
  }
}
