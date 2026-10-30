import 'package:http/http.dart' as http;

import '../models/analysis.dart';
import '../models/video.dart';
import 'api.dart';
import 'api_client.dart';
import 'api_error.dart';

// 백엔드 연결 필요: 이 파일 전체가 백엔드 대신 쓰는 예시 데이터다.
// USE_BACKEND=true로 실행하면 쓰이지 않는다 (core/config.dart).

String _iso(DateTime t) => t.toUtc().toIso8601String();

/// 백엔드 없이 화면을 보기 위한 가짜 API. 네트워크를 쓰지 않고 메모리 안의 예시 데이터만 바꾼다.
/// 목록의 영상마다 상태가 달라 각 화면을 눌러 볼 수 있다.
class DemoApi extends Api {
  DemoApi() : super(ApiClient(http.Client())) {
    final expires = _iso(DateTime.now().add(const Duration(days: 30)));
    void add(int id, String name, String status, [Map<String, Object?> extra = const {}]) {
      _videos[id] = {
        'video_id': id,
        'original_filename': name,
        'status': status,
        'input_done': false,
        'raw_deleted': false,
        'masked_deleted': false,
        'created_at': _iso(DateTime.now()),
        'duration_sec': 86400.0,
        'view_expires_at': expires,
        ...extra,
      };
    }

    add(1, '01_입력필요.mp4', VideoStatus.stage1Done);
    add(2, '02_확인가능.mp4', VideoStatus.ready);
    add(3, '03_결과.mp4', VideoStatus.finished);
    add(4, '04_대기중.mp4', VideoStatus.queued, {'queue_ahead': 2});
    add(5, '05_분석중.mp4', VideoStatus.stage2Running);
    add(6, '06_업로드중.mp4', VideoStatus.uploading, {'view_expires_at': null, 'duration_sec': null});
    add(7, '07_분석실패_재시도.mp4', VideoStatus.failed, {
      'error_kind': 'temporary',
      'can_retry': true,
      'retry_left': 2,
    });
    add(8, '08_분석실패_파일문제.mp4', VideoStatus.failed, {
      'error_kind': 'file',
      'can_retry': false,
      'retry_left': 3,
    });
    add(9, '09_후보없음.mp4', VideoStatus.exhausted, {'candidate_total': 0, 'candidate_unavailable': 0});
    add(10, '10_후보확인완료.mp4', VideoStatus.exhausted, {
      'candidate_total': 12,
      'candidate_unavailable': 2,
    });
    add(11, '11_보관기간종료.mp4', VideoStatus.finished, {
      'masked_deleted': true,
      'raw_deleted': true,
      'view_expires_at': _iso(DateTime.now().subtract(const Duration(days: 1))),
    });

    _pins[3] = [_pinOf(_clip(3, 1)), _pinOf(_clip(3, 3))];
  }

  static const _mainBatches = 3;
  static const _perBatch = 10; // 서버와 같은 묶음당 최대 개수 (01장)

  final _videos = <int, Map<String, Object?>>{};
  final _pins = <int, List<Map<String, Object?>>>{};
  final _mainBatch = <int, int>{}; // 영상별 지금 묶음 번호
  final _failedSeen = <int>{}; // 점수 미산출 탭을 넘긴 영상
  bool _loggedIn = false;

  Future<void> _wait() => Future<void>.delayed(const Duration(milliseconds: 200));

  Map<String, Object?> _video(int id) {
    final v = _videos[id];
    if (v == null) throw ApiException(404, 'VIDEO_NOT_FOUND');
    return v;
  }

  // 후보 클립 예시. 재생할 영상 파일은 없어 clip_url을 비워 둔다 (재생기가 안내를 보인다).
  Map<String, Object?> _clip(int videoId, int rank, {bool failed = false}) => {
    'candidate_clip_id': videoId * 1000 + (failed ? 500 : 0) + rank,
    'rank': rank,
    'vlm_score': failed ? null : 95 - rank * 5,
    'start_sec': 3600.0 * rank + 125,
    'end_sec': 3600.0 * rank + 155,
    'clip_url': '',
  };

  Map<String, Object?> _pinOf(Map<String, Object?> clip) => {
    'candidate_clip_id': clip['candidate_clip_id'],
    'start_sec': clip['start_sec'],
    'end_sec': clip['end_sec'],
    'est_start_at': _iso(DateTime.utc(2026, 9, 16, 15).add(Duration(seconds: (clip['start_sec'] as double).round()))),
    'est_end_at': _iso(DateTime.utc(2026, 9, 16, 15).add(Duration(seconds: (clip['end_sec'] as double).round()))),
    'clip_url': '',
    'pinned_at': _iso(DateTime.now()),
  };

  Map<String, Object?> _lists(int id) {
    final current = _mainBatch[id] ?? 1;
    final mainDone = current > _mainBatches;
    return {
      'main': {
        'latest_batch_no': mainDone ? _mainBatches : current,
        'remaining': mainDone ? 0 : (_mainBatches - current) * _perBatch,
        'done': mainDone,
        'unavailable': 1,
      },
      'parse_failed': {
        'latest_batch_no': 1,
        'remaining': 0,
        'done': _failedSeen.contains(id),
        'unavailable': 0,
      },
    };
  }

  // 계정
  @override
  Future<void> login(String loginId, String password) async {
    await _wait();
    _loggedIn = true;
  }

  @override
  Future<void> logout() async => _loggedIn = false;

  @override
  Future<void> me() async {
    if (!_loggedIn) throw ApiException(401, 'UNAUTHENTICATED');
  }

  // 업로드 링크·업로드
  @override
  Future<({String token, String expiresAt})> issueUploadLink() async {
    await _wait();
    return (
      token: 'demo-${DateTime.now().millisecondsSinceEpoch}',
      expiresAt: _iso(DateTime.now().add(const Duration(hours: 24))),
    );
  }

  @override
  Future<void> checkUploadToken(String token) async {
    await _wait();
    // 주소에 used·expired를 넣으면 링크 오류 안내를 볼 수 있다
    if (token == 'used') throw ApiException(410, 'UPLOAD_TOKEN_USED');
    if (token == 'expired') throw ApiException(410, 'UPLOAD_TOKEN_EXPIRED');
  }

  @override
  Future<String> presignUpload(
    String token, {
    required String filename,
    required int sizeBytes,
    String? recordingStartedAt,
    required Map<String, Object> agreement,
  }) async => 'demo://upload';

  @override
  Future<void> completeUpload(String token) async {}

  @override
  Future<void> warmup(String token) async {}

  // 영상
  @override
  Future<List<VideoSummary>> videos() async {
    await _wait();
    return [for (final v in _videos.values) VideoSummary.fromJson(v)];
  }

  @override
  Future<VideoDetail> video(int id) async {
    await _wait();
    return VideoDetail.fromJson(_video(id));
  }

  @override
  Future<void> retry(int id) async {
    _video(id)
      ..['status'] = VideoStatus.stage2Running
      ..remove('error_kind')
      ..remove('can_retry')
      ..remove('retry_left');
  }

  // 입력
  @override
  Future<Still> still(int id) async {
    await _wait();
    return Still.fromJson({
      'still_frame_id': id * 10,
      't_sec': 0.0,
      'image_url': 'demo/still.jpg', // web/demo/still.jpg (백엔드 가짜 워커와 같은 합성 이미지)
      'detections': [
        {'det_id': 1, 'bbox': [810, 440, 960, 620]},
        {'det_id': 2, 'bbox': [950, 435, 1120, 625]},
      ],
    });
  }

  @override
  Future<({String uploadUrl, String photoKey})> presignPhoto(
    int id, {
    required String filename,
    required int sizeBytes,
  }) async => (uploadUrl: 'demo://photo', photoKey: 'videos/$id/inputs/photo.jpg');

  @override
  Future<void> saveInput(int id, Map<String, Object> body) async {
    await _wait();
    _video(id)
      ..['input_done'] = true
      ..['queue_ahead'] = 1;
  }

  // 후보
  @override
  Future<Batch> batch(int id, {String? list, int? batchNo}) async {
    await _wait();
    final kind = list ?? CandidateList.main;
    final lists = _lists(id);
    final latest = (lists[kind] as Map)['latest_batch_no'] as int;
    final no = batchNo ?? latest;
    final failed = kind == CandidateList.parseFailed;
    return Batch.fromJson({
      'list': kind,
      'batch_no': no,
      'unavailable': failed || no != 1 ? 0 : 1,
      'candidates': failed
          ? [_clip(id, 1, failed: true), _clip(id, 2, failed: true)]
          : [for (var i = 1; i <= _perBatch; i++) _clip(id, (no - 1) * _perBatch + i)],
      'lists': lists,
    });
  }

  @override
  Future<NextBatchResult> nextBatch(int id, String list, int batchNo) async {
    await _wait();
    if (list == CandidateList.parseFailed) {
      _failedSeen.add(id);
    } else {
      _mainBatch[id] = batchNo + 1;
    }
    final lists = _lists(id);
    final allDone = (lists['main'] as Map)['done'] == true && (lists['parse_failed'] as Map)['done'] == true;
    if (allDone) {
      _video(id)
        ..['status'] = VideoStatus.exhausted
        ..['candidate_total'] = _mainBatches * _perBatch + 3
        ..['candidate_unavailable'] = 1;
    }
    return NextBatchResult.fromJson({
      'status': allDone ? VideoStatus.exhausted : VideoStatus.ready,
      'lists': lists,
    });
  }

  @override
  Future<List<PinnedIncident>> pin(int id, int candidateClipId) async {
    final rank = candidateClipId % 500;
    final failed = candidateClipId % 1000 >= 500;
    final pins = _pins.putIfAbsent(id, () => []);
    if (!pins.any((p) => p['candidate_clip_id'] == candidateClipId)) {
      pins.add(_pinOf(_clip(id, rank, failed: failed)));
    }
    return pinsFromJson(pins);
  }

  @override
  Future<List<PinnedIncident>> unpin(int id, int candidateClipId) async {
    final pins = _pins[id] ?? [];
    pins.removeWhere((p) => p['candidate_clip_id'] == candidateClipId);
    return pinsFromJson(pins);
  }

  @override
  Future<List<PinnedIncident>> pins(int id) async {
    await _wait();
    if (_video(id)['masked_deleted'] == true) throw ApiException(409, 'MASKED_EXPIRED');
    return pinsFromJson(_pins[id] ?? []);
  }

  @override
  Future<void> finish(int id) async => _video(id)['status'] = VideoStatus.finished;
}
