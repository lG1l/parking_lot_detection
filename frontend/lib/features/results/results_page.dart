import 'package:flutter/material.dart';

import '../../core/widgets/placeholder_page.dart';

class ResultsPage extends StatelessWidget {
  const ResultsPage({super.key, required this.videoId});

  final String videoId;

  @override
  Widget build(BuildContext context) {
    return const PlaceholderPage(title: '결과', spec: '2.9·2.10');
  }
}
