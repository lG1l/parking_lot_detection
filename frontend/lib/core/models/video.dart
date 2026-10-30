// 8·9번 응답 (05장 5.5).

/// 화면이 보는 `status` 값 (05장 5.5, 04장 4.3).
abstract final class VideoStatus {
  static const uploading = 'uploading';
  static const uploadFailed = 'upload_failed';
  static const queued = 'queued';
  static const stillsRunning = 'stills_running';
  static const stage1Done = 'stage1_done';
  static const stage2Running = 'stage2_running';
  static const ready = 'ready';
  static const batchRunning = 'batch_running';
  static const finished = 'finished';
  static const exhausted = 'exhausted';
  static const failed = 'failed';
}

/// 목록에 보일 상태 짧은 이름 (07장 2.2).
String statusLabel(String status) => switch (status) {
  VideoStatus.uploading => '업로드 중',
  VideoStatus.uploadFailed => '업로드 확인 안 됨',
  VideoStatus.queued => '대기 중',
  VideoStatus.stillsRunning => '준비 중',
  VideoStatus.stage1Done => '사전 입력 필요',
  VideoStatus.stage2Running => '분석 중',
  VideoStatus.ready || VideoStatus.batchRunning => '후보 선택 가능',
  VideoStatus.finished => '확인 완료',
  VideoStatus.exhausted => '확인 완료', // finished와 같은 이름 (D-186, D-190)
  VideoStatus.failed => '분석 실패',
  _ => status,
};

/// 목록 칩 색을 정하는 상태 묶음 (07장 2.2, D-183). ended는 보관 기간 종료 (D-186).
enum StatusGroup { todo, problem, waiting, done, ended }

StatusGroup statusGroup(String status) => switch (status) {
  VideoStatus.stage1Done || VideoStatus.ready || VideoStatus.batchRunning => StatusGroup.todo,
  VideoStatus.uploadFailed || VideoStatus.failed => StatusGroup.problem,
  VideoStatus.finished || VideoStatus.exhausted => StatusGroup.done,
  _ => StatusGroup.waiting,
};

class VideoSummary {
  VideoSummary({
    required this.videoId,
    required this.originalFilename,
    required this.status,
    required this.viewExpiresAt,
    required this.maskedDeleted,
    this.createdAt,
  });

  factory VideoSummary.fromJson(Map<String, dynamic> j) => VideoSummary(
    videoId: j['video_id'] as int,
    originalFilename: j['original_filename'] as String,
    status: j['status'] as String,
    viewExpiresAt: j['view_expires_at'] as String?,
    maskedDeleted: j['masked_deleted'] as bool,
    createdAt: j['created_at'] as String?,
  );

  final int videoId;
  final String originalFilename;
  final String status;
  final String? viewExpiresAt;

  /// 영상 행을 만든 시각 = 관리자가 업로드를 시작한 시각(6번 URL 발급, 04장). 목록의 업로드 날짜 (D-190).
  final String? createdAt;

  /// 마스킹본을 더 볼 수 없는지. 파기됐거나 열람기한이 지났으면 서버가 true로 준다 (D-187).
  final bool maskedDeleted;

  /// 보관 기간이 끝났으면 상태와 관계없이 "종료됨" (D-186, D-187).
  String get listLabel => maskedDeleted ? '종료됨' : statusLabel(status);

  StatusGroup get listGroup => maskedDeleted ? StatusGroup.ended : statusGroup(status);
}

class VideoDetail {
  VideoDetail({
    required this.videoId,
    required this.originalFilename,
    required this.status,
    this.queueAhead,
    required this.inputDone,
    this.candidateTotal,
    this.candidateUnavailable,
    required this.rawDeleted,
    required this.maskedDeleted,
    this.durationSec,
    this.errorKind,
    this.canRetry,
    this.retryLeft,
    this.viewExpiresAt,
  });

  factory VideoDetail.fromJson(Map<String, dynamic> j) => VideoDetail(
    videoId: j['video_id'] as int,
    originalFilename: j['original_filename'] as String,
    status: j['status'] as String,
    queueAhead: j['queue_ahead'] as int?,
    inputDone: j['input_done'] as bool? ?? false,
    candidateTotal: j['candidate_total'] as int?,
    candidateUnavailable: j['candidate_unavailable'] as int?,
    rawDeleted: j['raw_deleted'] as bool? ?? false,
    maskedDeleted: j['masked_deleted'] as bool? ?? false,
    durationSec: (j['duration_sec'] as num?)?.toDouble(),
    errorKind: j['error_kind'] as String?,
    canRetry: j['can_retry'] as bool?,
    retryLeft: j['retry_left'] as int?,
    viewExpiresAt: j['view_expires_at'] as String?,
  );

  final int videoId;
  final String originalFilename;
  final String status;
  final int? queueAhead;
  final bool inputDone;
  final int? candidateTotal;
  final int? candidateUnavailable;
  final bool rawDeleted;
  final bool maskedDeleted;
  final double? durationSec;
  final String? errorKind;
  final bool? canRetry;
  final int? retryLeft;
  final String? viewExpiresAt;
}
