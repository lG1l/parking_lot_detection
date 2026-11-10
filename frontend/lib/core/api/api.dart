import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/account.dart';
import '../models/analysis.dart';
import '../models/video.dart';
import 'api_client.dart';
import 'demo_api.dart';

/// 05장 엔드포인트. 메서드 이름 옆 번호는 05장 번호다.
class Api {
  Api(this._c);

  final ApiClient _c;

  // 계정 (5.3)
  Future<Me> login(String loginId, String password) async =>
      Me.fromJson(await _c.post('/api/auth/login', {'login_id': loginId, 'password': password})); // 1
  Future<void> logout() => _c.post('/api/auth/logout'); // 2
  Future<Me> me() async => Me.fromJson(await _c.get('/api/auth/me')); // 3

  // 사건·업로드 (5.4). 관리자 계정만 부른다 (D-204)
  Future<({String loginId, String maskedName})> lookupInvitee(String loginId) async {
    final j = await _c.get('/api/users/lookup', query: {'login_id': loginId}); // 24
    return (loginId: j['login_id'] as String, maskedName: j['masked_name'] as String);
  }

  Future<VideoCase> createCase(String victimLoginId) async =>
      VideoCase.fromJson(await _c.post('/api/cases', {'victim_login_id': victimLoginId})); // 21

  Future<List<VideoCase>> cases() async {
    final j = await _c.get('/api/cases'); // 22
    return [for (final e in j['items'] as List) VideoCase.fromJson(e as Map<String, dynamic>)];
  }

  /// 피해자가 사건 초대를 수락한다. 피해자 계정만 부른다 (D-233 초안, 백엔드 미구현)
  Future<void> acceptCase(int caseId) => _c.post('/api/cases/$caseId/accept'); // 26

  Future<void> agreeViewing(int videoId) =>
      _c.post('/api/videos/$videoId/viewing-agreement', {'confirm_supervision': true}); // 23

  Future<({int videoId, String uploadUrl})> presignUpload(
    int caseId, {
    required String filename,
    required int sizeBytes,
    String? recordingStartedAt,
    required Map<String, Object> agreement,
  }) async {
    final j = await _c.post('/api/cases/$caseId/uploads/presign', {
      'filename': filename,
      'size_bytes': sizeBytes,
      'recording_started_at': ?recordingStartedAt,
      'agreement': agreement,
    }); // 6
    return (videoId: j['video_id'] as int, uploadUrl: j['upload_url'] as String);
  }

  Future<void> completeUpload(int videoId) => _c.post('/api/videos/$videoId/upload/complete'); // 7
  Future<void> warmup(int videoId) => _c.post('/api/videos/$videoId/upload/warmup'); // 16

  // 영상 (5.5)
  Future<List<VideoSummary>> videos() async {
    final j = await _c.get('/api/videos') as List; // 8
    return j.map((e) => VideoSummary.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<VideoDetail> video(int id) async =>
      VideoDetail.fromJson(await _c.get('/api/videos/$id')); // 9

  Future<void> retry(int id) => _c.post('/api/videos/$id/retry'); // 19

  // 입력 (5.6, 5.7)
  Future<Still> still(int id) async =>
      Still.fromJson(await _c.get('/api/videos/$id/still')); // 10

  Future<({String uploadUrl, String photoKey})> presignPhoto(
    int id, {
    required String filename,
    required int sizeBytes,
  }) async {
    final j = await _c.post('/api/videos/$id/input/photo', {
      'filename': filename,
      'size_bytes': sizeBytes,
    }); // 18
    return (uploadUrl: j['upload_url'] as String, photoKey: j['photo_key'] as String);
  }

  Future<void> saveInput(int id, Map<String, Object> body) =>
      _c.put('/api/videos/$id/input', body); // 11

  // 후보 (5.8, 5.9)
  Future<Batch> batch(int id, {String? list, int? batchNo}) async {
    final query = <String, String>{'list': ?list, 'batch_no': ?batchNo?.toString()};
    return Batch.fromJson(
      await _c.get('/api/videos/$id/batch', query: query.isEmpty ? null : query),
    ); // 12
  }

  Future<NextBatchResult> nextBatch(int id, String list, int batchNo) async =>
      NextBatchResult.fromJson(
        await _c.post('/api/videos/$id/batch/next', {'list': list, 'batch_no': batchNo}),
      ); // 13

  Future<List<PinnedIncident>> pin(int id, int candidateClipId) async =>
      pinsFromJson(await _c.post('/api/videos/$id/pin', {'candidate_clip_id': candidateClipId})); // 14

  Future<List<PinnedIncident>> pins(int id) async =>
      pinsFromJson(await _c.get('/api/videos/$id/pin')); // 15

  Future<List<PinnedIncident>> unpin(int id, int candidateClipId) async =>
      pinsFromJson(await _c.delete('/api/videos/$id/pin/$candidateClipId')); // 20

  Future<void> finish(int id) => _c.post('/api/videos/$id/finish'); // 17

  /// 사건 지점 시간. 두 계정이 부르고, 재생 URL은 없다. 끝 상태 전에는 빈 배열이다 (D-210).
  Future<List<PinnedIncident>> incidentTimes(int id) async =>
      pinsFromJson(await _c.get('/api/videos/$id/incident-times')); // 25
}

// 백엔드 연결 필요: USE_BACKEND=true면 실제 API, 아니면 예시 데이터(DemoApi)
final apiProvider = Provider<Api>(
  (ref) => useBackend ? Api(ApiClient(http.Client())) : DemoApi(),
);
