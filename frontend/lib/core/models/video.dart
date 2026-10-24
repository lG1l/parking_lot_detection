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
  VideoStatus.stage1Done => '입력 필요',
  VideoStatus.stage2Running => '분석 중',
  VideoStatus.ready || VideoStatus.batchRunning => '확인 가능',
  VideoStatus.finished => '확인 끝남',
  VideoStatus.exhausted => '후보 확인 완료',
  VideoStatus.failed => '분석 실패',
  _ => status,
};

class VideoSummary {
  VideoSummary({
    required this.videoId,
    required this.originalFilename,
    required this.status,
    required this.viewExpiresAt,
  });

  factory VideoSummary.fromJson(Map<String, dynamic> j) => VideoSummary(
    videoId: j['video_id'] as int,
    originalFilename: j['original_filename'] as String,
    status: j['status'] as String,
    viewExpiresAt: j['view_expires_at'] as String?,
  );

  final int videoId;
  final String originalFilename;
  final String status;
  final String? viewExpiresAt;
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
