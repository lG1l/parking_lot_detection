import 'package:go_router/go_router.dart';

import '../features/admin_upload/admin_upload_page.dart';
import '../features/auth/login_page.dart';
import '../features/auth/start_page.dart';
import '../features/candidates/candidates_page.dart';
import '../features/damage_input/damage_input_page.dart';
import '../features/results/results_page.dart';
import '../features/video_status/video_status_page.dart';
import '../features/videos/upload_link_page.dart';
import '../features/videos/video_list_page.dart';

// 웹 기본 주소 형식은 /#/경로다 (03장 3.2). 관리자 업로드 주소는 /#/upload/{token} (07장).
// 주소 목록은 D-179. `/`는 3번으로 로그인 여부를 보고 목록이나 로그인으로 보낸다.
// 모든 경로를 한 단계로 둔다. 중첩하면 go_router가 상위 화면도 함께 만들어
// 목록(8번)이나 상태 화면(9번 주기 조회)이 뒤에서 같이 돈다.
GoRouter createRouter({String initialLocation = '/'}) => GoRouter(
  initialLocation: initialLocation,
  routes: [
    GoRoute(path: '/', builder: (_, _) => const StartPage()),
    GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
    GoRoute(path: '/videos', builder: (_, _) => const VideoListPage()),
    GoRoute(path: '/videos/upload-link', builder: (_, _) => const UploadLinkPage()),
    GoRoute(
      path: '/videos/:videoId',
      builder: (_, state) => VideoStatusPage(
        videoId: state.pathParameters['videoId']!,
        expired: state.uri.queryParameters['expired'] == '1',
      ),
    ),
    GoRoute(
      path: '/videos/:videoId/input',
      builder: (_, state) => DamageInputPage(videoId: state.pathParameters['videoId']!),
    ),
    GoRoute(
      path: '/videos/:videoId/candidates',
      builder: (_, state) => CandidatesPage(videoId: state.pathParameters['videoId']!),
    ),
    GoRoute(
      path: '/videos/:videoId/results',
      builder: (_, state) => ResultsPage(videoId: state.pathParameters['videoId']!),
    ),
    GoRoute(
      path: '/upload/:token',
      builder: (_, state) => AdminUploadPage(token: state.pathParameters['token']!),
    ),
  ],
);
