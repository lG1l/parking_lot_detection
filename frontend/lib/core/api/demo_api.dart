import 'dart:math' as math;

import 'package:http/http.dart' as http;

import '../models/account.dart';
import '../models/analysis.dart';
import '../models/video.dart';
import 'api.dart';
import 'api_client.dart';
import 'api_error.dart';

// 백엔드 연결 필요: 이 파일 전체가 백엔드 대신 쓰는 예시 데이터다.
// USE_BACKEND=true로 실행하면 쓰이지 않는다 (core/config.dart).

String _iso(DateTime t) => t.toUtc().toIso8601String();

/// 10번 응답의 탐지 1건. `bbox`는 손으로 정한 `polygon`을 감싸는 사각형으로 만든다 (05장 5.6).
Map<String, Object?> _demoCar(int detId, List<List<int>> polygon) {
  final xs = polygon.map((p) => p[0]);
  final ys = polygon.map((p) => p[1]);
  return {
    'det_id': detId,
    'bbox': [xs.reduce(math.min), ys.reduce(math.min), xs.reduce(math.max), ys.reduce(math.max)],
    'polygon': polygon,
  };
}

/// 데모 업로드 주소. 관리자 업로드 화면은 이 주소면 S3에 보내지 않고 올린 것으로 본다.
const demoUploadUrl = 'demo://upload';

/// 백엔드 없이 화면을 보기 위한 가짜 API. 네트워크를 쓰지 않고 메모리 안의 예시 데이터만 바꾼다.
/// 목록의 영상마다 상태가 달라 각 화면을 눌러 볼 수 있다.
/// 아이디가 `victim`으로 시작하면 피해자 계정, 그 밖은 관리자 계정으로 로그인한다 (D-204).
class DemoApi extends Api {
  DemoApi() : super(ApiClient(http.Client())) {
    final expires = _iso(DateTime.now().add(const Duration(days: 30)));
    void add(int id, int caseId, String name, String status, [Map<String, Object?> extra = const {}]) {
      _videos[id] = {
        'video_id': id,
        'case_id': caseId,
        'original_filename': name,
        'status': status,
        'input_done': false,
        'raw_deleted': false,
        'masked_deleted': false,
        'created_at': _iso(DateTime.now().subtract(Duration(hours: id))),
        'duration_sec': 86400.0,
        'view_expires_at': expires,
        ...extra,
      };
    }

    void addCase(int id, String name, String victim, {bool accepted = true}) {
      final created = DateTime.now().subtract(Duration(days: id));
      _cases[id] = {
        'id': id,
        'case_name': name,
        'admin_name': 'parking_admin',
        'victim_name': victim,
        'created_at': _iso(created),
        'accepted_at': accepted ? _iso(created.add(const Duration(hours: 1))) : null,
      };
    }

    addCase(1, 'B2 기둥 옆 긁힘', 'victim01');
    addCase(2, '지하 1층 범퍼 파손', 'victim02');
    // 연결만 하고 영상을 아직 올리지 않은 사건. 관리자 목록에서 누르면 업로드 화면으로 간다
    addCase(3, '입구 쪽 문콕', 'victim03');
    // 피해자가 아직 수락하지 않은 사건. 피해자 [알림]에 뜨고, 수락하면 영상 12가 목록에 보인다 (D-233)
    addCase(4, '출구 앞 사이드미러', 'victim01', accepted: false);

    add(1, 1, '01_입력필요.mp4', VideoStatus.stage1Done);
    add(2, 1, '02_확인가능.mp4', VideoStatus.ready);
    add(3, 1, '03_결과.mp4', VideoStatus.finished);
    add(4, 1, '04_대기중.mp4', VideoStatus.queued, {'queue_ahead': 2});
    add(5, 1, '05_분석중.mp4', VideoStatus.stage2Running);
    add(6, 1, '06_업로드중.mp4', VideoStatus.uploading, {'view_expires_at': null, 'duration_sec': null});
    add(7, 2, '07_분석실패_재시도.mp4', VideoStatus.failed, {
      'error_kind': 'temporary',
      'can_retry': true,
      'retry_left': 2,
    });
    add(8, 2, '08_분석실패_파일문제.mp4', VideoStatus.failed, {
      'error_kind': 'file',
      'can_retry': false,
      'retry_left': 3,
    });
    add(9, 2, '09_후보없음.mp4', VideoStatus.exhausted, {'candidate_total': 0, 'candidate_unavailable': 0});
    add(10, 2, '10_후보확인완료.mp4', VideoStatus.exhausted, {
      'candidate_total': 12,
      'candidate_unavailable': 2,
    });
    add(11, 2, '11_보관기간종료.mp4', VideoStatus.finished, {
      'masked_deleted': true,
      'raw_deleted': true,
      'view_expires_at': _iso(DateTime.now().subtract(const Duration(days: 1))),
    });
    add(12, 4, '12_수락대기.mp4', VideoStatus.stage1Done);

    _pins[3] = [_pinOf(_clip(3, 1)), _pinOf(_clip(3, 3))];
  }

  static const _mainBatches = 3;
  static const _perBatch = 10; // 서버와 같은 묶음당 최대 개수 (01장)

  final _videos = <int, Map<String, Object?>>{};
  final _cases = <int, Map<String, Object?>>{};
  final _agreed = <int>{}; // 관리·감독 안내에 동의한 영상 (23번)
  final _pins = <int, List<Map<String, Object?>>>{};
  final _mainBatch = <int, int>{}; // 영상별 지금 묶음 번호
  final _failedSeen = <int>{}; // 점수 미산출 탭을 넘긴 영상
  Me? _me;

  bool get _admin => _me?.isAdmin ?? false;

  Future<void> _wait() => Future<void>.delayed(const Duration(milliseconds: 200));

  Map<String, Object?> _video(int id) {
    final v = _videos[id];
    if (v == null) throw ApiException(404, 'VIDEO_NOT_FOUND');
    return v;
  }

  /// 피해자 계정에서 감출 영상인지. 수락 전 사건의 영상은 피해자에게 주지 않는다 (D-233)
  bool _hiddenFromVictim(Map<String, Object?> v) => !_admin && _cases[v['case_id']]?['accepted_at'] == null;

  /// 후보·고정 API는 관리자 계정에서, 안내창 동의 뒤에만 허용한다 (D-204).
  void _checkViewing(int id) {
    if (!_admin) throw ApiException(403, 'ROLE_NOT_ALLOWED');
    if (!_agreed.contains(id)) throw ApiException(403, 'SUPERVISION_AGREEMENT_REQUIRED');
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
  Future<Me> login(String loginId, String password) async {
    await _wait();
    final victim = loginId.startsWith('victim');
    return _me = Me(id: victim ? 2 : 1, loginId: loginId, name: loginId, role: victim ? 'victim' : 'admin');
  }

  @override
  Future<void> logout() async => _me = null;

  @override
  Future<Me> me() async {
    final me = _me;
    if (me == null) throw ApiException(401, 'UNAUTHENTICATED');
    return me;
  }

  // 사건·업로드
  @override
  Future<({String loginId, String maskedName})> lookupInvitee(String loginId) async {
    await _wait();
    // 아이디가 victim으로 시작하지 않으면 없는 피해자 계정으로 본다
    if (!loginId.startsWith('victim')) throw ApiException(422, 'INVITEE_INVALID');
    return (loginId: loginId, maskedName: '홍*동');
  }

  @override
  Future<VideoCase> createCase(String victimLoginId, {required String caseName}) async {
    await _wait();
    // 아이디가 victim으로 시작하지 않으면 없는 피해자 계정으로 본다
    if (!victimLoginId.startsWith('victim')) throw ApiException(422, 'INVITEE_INVALID');
    final id = _cases.keys.fold(0, (a, b) => a > b ? a : b) + 1;
    _cases[id] = {
      'id': id,
      'case_name': caseName,
      'admin_name': _me?.name ?? 'parking_admin',
      'victim_name': victimLoginId,
      'created_at': _iso(DateTime.now()),
      'accepted_at': null, // 피해자가 [알림]에서 수락해야 묶인다 (D-233)
    };
    return VideoCase.fromJson(_cases[id]!);
  }

  // 22번은 피해자에게도 수락 전 사건을 준다. [알림] 목록에 필요하다 (D-233)
  @override
  Future<List<VideoCase>> cases() async {
    await _wait();
    final items = _cases.values.toList()
      ..sort((a, b) => (b['created_at'] as String).compareTo(a['created_at'] as String));
    return [for (final c in items) VideoCase.fromJson(c)];
  }

  Map<String, Object?> _case(int caseId) {
    final c = _cases[caseId];
    // 데모 피해자는 모든 사건의 피해자로 친다
    if (c == null) throw ApiException(404, 'CASE_NOT_FOUND');
    return c;
  }

  @override
  Future<VideoCase> renameCase(int caseId, String caseName) async {
    await _wait();
    if (caseName.trim().isEmpty) throw ApiException(422, 'VALIDATION_FAILED');
    final c = _case(caseId)..['case_name'] = caseName.trim();
    return VideoCase.fromJson(c);
  }

  /// 사건과 그 사건의 영상을 함께 지운다. 실제 서버에서 영상·기록을 어떻게 지울지는 팀원 2가 정한다 (D-237)
  @override
  Future<void> deleteCase(int caseId) async {
    await _wait();
    _case(caseId);
    _cases.remove(caseId);
    _videos.removeWhere((_, v) => v['case_id'] == caseId);
  }

  @override
  Future<void> acceptCase(int caseId) async {
    await _wait();
    if (_admin) throw ApiException(403, 'ROLE_NOT_ALLOWED');
    final c = _cases[caseId];
    if (c == null) throw ApiException(404, 'CASE_NOT_FOUND');
    c['accepted_at'] ??= _iso(DateTime.now()); // 이미 수락했으면 그대로 성공
  }

  @override
  Future<void> agreeViewing(int videoId) async {
    await _wait();
    _agreed.add(videoId);
  }

  @override
  Future<({int videoId, String uploadUrl})> presignUpload(
    int caseId, {
    required String filename,
    required int sizeBytes,
    String? recordingStartedAt,
    required Map<String, Object> agreement,
  }) async {
    await _wait();
    if (!_cases.containsKey(caseId)) throw ApiException(404, 'CASE_NOT_FOUND');
    final id = _videos.keys.fold(0, (a, b) => a > b ? a : b) + 1;
    _videos[id] = {
      'video_id': id,
      'case_id': caseId,
      'original_filename': filename,
      'status': VideoStatus.uploading,
      'input_done': false,
      'raw_deleted': false,
      'masked_deleted': false,
      'created_at': _iso(DateTime.now()),
      'duration_sec': null,
      'view_expires_at': null,
    };
    return (videoId: id, uploadUrl: demoUploadUrl);
  }

  @override
  Future<void> completeUpload(int videoId) async {
    // 1단계(정지 장면)까지 끝난 것으로 둔다. 피해자 계정으로 입력 화면을 볼 수 있다
    _video(videoId)
      ..['status'] = VideoStatus.stage1Done
      ..['duration_sec'] = 86400.0
      ..['view_expires_at'] = _iso(DateTime.now().add(const Duration(days: 30)));
  }

  @override
  Future<void> warmup(int videoId) async {}

  // 영상
  @override
  Future<List<VideoSummary>> videos() async {
    await _wait();
    final items = _videos.values.where((v) => !_hiddenFromVictim(v)).toList()
      ..sort((a, b) => (b['created_at'] as String).compareTo(a['created_at'] as String));
    return [for (final v in items) VideoSummary.fromJson(v)];
  }

  @override
  Future<VideoDetail> video(int id) async {
    await _wait();
    final v = _video(id);
    if (_hiddenFromVictim(v)) throw ApiException(404, 'VIDEO_NOT_FOUND');
    return VideoDetail.fromJson(v);
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
      // web/demo/still.jpg: 지하주차장 사진 2000x1500, 번호판은 흐리게 처리 (10장 still-masked.jpg).
      // detections는 사진을 보고 손으로 정한 좌표다. 오른쪽 줄의 White SUV 두 대(det 3·4)와
      // 검은 세단(det 5)은 일부러 서로 겹치게 두어 "넓이가 작은 것, 다시 누르면 다음 것"을 볼 수 있다 (D-221).
      'image_url': 'demo/still.jpg',
      'detections': [
        _demoCar(1, [[0, 1145], [70, 1140], [150, 1160], [178, 1200], [178, 1260], [150, 1310], [70, 1335], [0, 1340]]),
        _demoCar(2, [[770, 1000], [800, 975], [880, 945], [960, 928], [1010, 928], [1010, 1030], [960, 1050], [880, 1058], [830, 1055], [790, 1040]]),
        _demoCar(3, [[915, 1000], [940, 960], [1000, 925], [1100, 895], [1310, 893], [1310, 960], [1100, 1000], [1040, 1030], [1010, 1050], [960, 1065], [920, 1050]]),
        _demoCar(4, [[1045, 1040], [1075, 1005], [1200, 940], [1290, 910], [1400, 900], [1490, 905], [1490, 960], [1400, 990], [1300, 1030], [1220, 1075], [1150, 1105], [1070, 1105], [1045, 1090]]),
        _demoCar(5, [[1152, 1085], [1175, 1060], [1300, 1000], [1400, 950], [1480, 935], [1500, 940], [1500, 1100], [1420, 1130], [1300, 1170], [1220, 1190], [1165, 1170], [1150, 1120]]),
        _demoCar(6, [[1355, 1100], [1385, 1060], [1440, 1035], [1500, 1025], [1510, 1030], [1510, 1245], [1440, 1250], [1380, 1235], [1357, 1200]]),
        // 기둥 뒤에 있는 차: 기둥에 끊긴 조각을 이은 영역이라 기둥 위까지 걸친다
        _demoCar(7, [[1710, 930], [1900, 925], [2000, 935], [2000, 1070], [1930, 1090], [1830, 1100], [1740, 1085], [1710, 1000]]),
        _demoCar(8, [[1745, 1260], [1760, 1190], [1850, 1130], [1930, 1095], [2000, 1070], [2000, 1500], [1780, 1500], [1750, 1420], [1745, 1330]]),
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
    _checkViewing(id);
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
    _checkViewing(id);
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
    _checkViewing(id);
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
    _checkViewing(id);
    final pins = _pins[id] ?? [];
    pins.removeWhere((p) => p['candidate_clip_id'] == candidateClipId);
    return pinsFromJson(pins);
  }

  @override
  Future<List<PinnedIncident>> pins(int id) async {
    await _wait();
    if (_video(id)['masked_deleted'] == true) throw ApiException(409, 'MASKED_EXPIRED');
    _checkViewing(id);
    return pinsFromJson(_pins[id] ?? []);
  }

  @override
  Future<List<PinnedIncident>> incidentTimes(int id) async {
    await _wait();
    final v = _video(id);
    if (v['masked_deleted'] == true) throw ApiException(409, 'MASKED_EXPIRED');
    // 끝 상태에서만 준다. 재생 URL·후보 번호는 없다 (D-210)
    if (v['status'] != VideoStatus.finished && v['status'] != VideoStatus.exhausted) return [];
    return pinsFromJson([
      for (final p in _pins[id] ?? [])
        {for (final e in p.entries) if (e.key != 'clip_url' && e.key != 'candidate_clip_id') e.key: e.value},
    ]);
  }

  @override
  Future<void> finish(int id) async {
    _checkViewing(id);
    _video(id)['status'] = VideoStatus.finished;
  }
}
