import 'package:flutter/material.dart';

/// 화면을 만들기 전까지 쓰는 임시 화면. 07장 절 번호를 함께 보여 준다.
class PlaceholderPage extends StatelessWidget {
  const PlaceholderPage({super.key, required this.title, required this.spec});

  final String title;
  final String spec;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(child: Text('$title (07장 $spec) — 준비 중')),
    );
  }
}
