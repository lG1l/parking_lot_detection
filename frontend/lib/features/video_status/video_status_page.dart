import 'package:flutter/material.dart';

import '../../core/widgets/placeholder_page.dart';

class VideoStatusPage extends StatelessWidget {
  const VideoStatusPage({super.key, required this.videoId});

  final String videoId;

  @override
  Widget build(BuildContext context) {
    return const PlaceholderPage(title: '영상 상태', spec: '2.5');
  }
}
