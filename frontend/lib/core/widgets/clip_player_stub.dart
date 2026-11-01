import 'package:flutter/material.dart';

import '../../app/theme.dart';

/// 테스트(VM)용 자리 표시. 실제 재생은 웹에서만 한다.
Widget buildClipVideo({required String url, VoidCallback? onUrlExpired}) => const Center(
  child: Text('영상', style: TextStyle(color: offWhiteColor)),
);
