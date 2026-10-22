import 'package:flutter/material.dart';

import '../../core/widgets/placeholder_page.dart';

class DamageInputPage extends StatelessWidget {
  const DamageInputPage({super.key, required this.videoId});

  final String videoId;

  @override
  Widget build(BuildContext context) {
    return const PlaceholderPage(title: '차량·파손 부위 입력', spec: '2.6');
  }
}
