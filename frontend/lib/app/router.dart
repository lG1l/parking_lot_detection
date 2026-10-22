import 'package:go_router/go_router.dart';

import '../features/admin_upload/admin_upload_page.dart';
import '../features/auth/login_page.dart';
import '../features/candidates/candidates_page.dart';
import '../features/damage_input/damage_input_page.dart';
import '../features/results/results_page.dart';
import '../features/video_status/video_status_page.dart';
import '../features/videos/upload_link_page.dart';
import '../features/videos/video_list_page.dart';

// 웹 기본 주소 형식은 /#/경로다 (03장 3.2). 관리자 업로드 주소는 /#/upload/{token} (07장).
final router = GoRouter(
  initialLocation: '/videos',
  routes: [
    GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
    GoRoute(
      path: '/videos',
      builder: (_, _) => const VideoListPage(),
      routes: [
        GoRoute(
          path: 'upload-link',
          builder: (_, _) => const UploadLinkPage(),
        ),
        GoRoute(
          path: ':videoId',
          builder: (_, state) =>
              VideoStatusPage(videoId: state.pathParameters['videoId']!),
          routes: [
            GoRoute(
              path: 'input',
              builder: (_, state) =>
                  DamageInputPage(videoId: state.pathParameters['videoId']!),
            ),
            GoRoute(
              path: 'candidates',
              builder: (_, state) =>
                  CandidatesPage(videoId: state.pathParameters['videoId']!),
            ),
            GoRoute(
              path: 'results',
              builder: (_, state) =>
                  ResultsPage(videoId: state.pathParameters['videoId']!),
            ),
          ],
        ),
      ],
    ),
    GoRoute(
      path: '/upload/:token',
      builder: (_, state) =>
          AdminUploadPage(token: state.pathParameters['token']!),
    ),
  ],
);
