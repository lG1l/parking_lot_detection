import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/analysis.dart';
import '../models/video.dart';
import 'api_client.dart';
import 'demo_api.dart';

/// 05장 엔드포인트. 메서드 이름 옆 번호는 05장 번호다.
class Api {
  Api(this._c);

  final ApiClient _c;

  // 계정 (5.3)
  Future<void> login(String loginId, String password) =>
      _c.post('/api/auth/login', {'login_id': loginId, 'password': password}); // 1
  Future<void> logout() => _c.post('/api/auth/logout'); // 2
  Future<void> me() => _c.get('/api/auth/me'); // 3

  // 업로드 링크·업로드 (5.4)
  Future<({String token, String expiresAt})> issueUploadLink() async {
    final j = await _c.post('/api/upload-links'); // 4
    return (token: j['token'] as String, expiresAt: j['expires_at'] as String);
  }

  Future<void> checkUploadToken(String token) =>
      _c.get('/api/uploads/${Uri.encodeComponent(token)}'); // 5

  Future<String> presignUpload(
    String token, {
    required String filename,
    required int sizeBytes,
    String? recordingStartedAt,
    required Map<String, Object> agreement,
  }) async {
    final j = await _c.post('/api/uploads/${Uri.encodeComponent(token)}/presign', {
      'filename': filename,
      'size_bytes': sizeBytes,
      'recording_started_at': ?recordingStartedAt,
      'agreement': agreement,
    }); // 6
    return j['upload_url'] as String;
  }

  Future<void> completeUpload(String token) =>
      _c.post('/api/uploads/${Uri.encodeComponent(token)}/complete'); // 7
  Future<void> warmup(String token) =>
      _c.post('/api/uploads/${Uri.encodeComponent(token)}/warmup'); // 16

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

  Future<void> finish(int id) => _c.post('/api/videos/$id/finish'); // 17
}

// 백엔드 연결 필요: USE_BACKEND=true면 실제 API, 아니면 예시 데이터(DemoApi)
final apiProvider = Provider<Api>(
  (ref) => useBackend ? Api(ApiClient(http.Client())) : DemoApi(),
);
