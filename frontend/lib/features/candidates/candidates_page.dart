import 'package:flutter/material.dart';

import '../../core/widgets/placeholder_page.dart';

class CandidatesPage extends StatelessWidget {
  const CandidatesPage({super.key, required this.videoId});

  final String videoId;

  @override
  Widget build(BuildContext context) {
    return const PlaceholderPage(title: '후보 확인', spec: '2.7·2.8');
  }
}
