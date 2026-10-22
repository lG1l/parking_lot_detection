import 'package:flutter/material.dart';

import '../../core/widgets/placeholder_page.dart';

class AdminUploadPage extends StatelessWidget {
  const AdminUploadPage({super.key, required this.token});

  final String token;

  @override
  Widget build(BuildContext context) {
    return const PlaceholderPage(title: '관리자 업로드', spec: '2.4');
  }
}
