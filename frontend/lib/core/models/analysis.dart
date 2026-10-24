// 10·12·13·14·15번 응답 (05장 5.6, 5.8, 5.9).

typedef Box = List<int>; // [x1, y1, x2, y2], 원본 해상도 픽셀

Box _box(dynamic v) => (v as List).map((e) => (e as num).toInt()).toList();

class Detection {
  Detection(this.detId, this.bbox);

  factory Detection.fromJson(Map<String, dynamic> j) =>
      Detection(j['det_id'] as int, _box(j['bbox']));

  final int detId;
  final Box bbox;
}

class Still {
  Still({
    required this.stillFrameId,
    required this.imageUrl,
    required this.detections,
  });

  factory Still.fromJson(Map<String, dynamic> j) => Still(
    stillFrameId: j['still_frame_id'] as int,
    imageUrl: j['image_url'] as String,
    detections: (j['detections'] as List)
        .map((e) => Detection.fromJson(e as Map<String, dynamic>))
        .toList(),
  );

  final int stillFrameId;
  final String imageUrl;
  final List<Detection> detections;
}

/// 후보군 목록과 파싱 실패 목록 (D-93, D-99).
abstract final class CandidateList {
  static const main = 'main';
  static const parseFailed = 'parse_failed';

  static String other(String list) => list == main ? parseFailed : main;
}

class ListSummary {
  ListSummary({
    required this.latestBatchNo,
    required this.remaining,
    required this.done,
    required this.unavailable,
  });

  factory ListSummary.fromJson(Map<String, dynamic> j) => ListSummary(
    latestBatchNo: j['latest_batch_no'] as int?,
    remaining: j['remaining'] as int,
    done: j['done'] as bool,
    unavailable: j['unavailable'] as int? ?? 0,
  );

  final int? latestBatchNo;
  final int remaining;
  final bool done;
  final int unavailable;
}

Map<String, ListSummary> listsFromJson(Map<String, dynamic> j) => {
  for (final e in j.entries)
    e.key: ListSummary.fromJson(e.value as Map<String, dynamic>),
};

class CandidateClip {
  CandidateClip({
    required this.candidateClipId,
    required this.rank,
    required this.vlmScore,
    required this.startSec,
    required this.endSec,
    required this.clipUrl,
  });

  factory CandidateClip.fromJson(Map<String, dynamic> j) => CandidateClip(
    candidateClipId: j['candidate_clip_id'] as int,
    rank: j['rank'] as int,
    vlmScore: (j['vlm_score'] as num?)?.toDouble(),
    startSec: (j['start_sec'] as num).toDouble(),
    endSec: (j['end_sec'] as num).toDouble(),
    clipUrl: j['clip_url'] as String,
  );

  final int candidateClipId;
  final int rank;
  final double? vlmScore;
  final double startSec;
  final double endSec;
  final String clipUrl;
}

class Batch {
  Batch({
    required this.list,
    required this.batchNo,
    required this.unavailable,
    required this.candidates,
    required this.lists,
  });

  factory Batch.fromJson(Map<String, dynamic> j) => Batch(
    list: j['list'] as String,
    batchNo: j['batch_no'] as int,
    unavailable: j['unavailable'] as int? ?? 0,
    candidates: (j['candidates'] as List)
        .map((e) => CandidateClip.fromJson(e as Map<String, dynamic>))
        .toList(),
    lists: listsFromJson(j['lists'] as Map<String, dynamic>),
  );

  final String list;
  final int batchNo;
  final int unavailable;
  final List<CandidateClip> candidates;
  final Map<String, ListSummary> lists;
}

class NextBatchResult {
  NextBatchResult(this.status, this.lists);

  factory NextBatchResult.fromJson(Map<String, dynamic> j) => NextBatchResult(
    j['status'] as String,
    listsFromJson(j['lists'] as Map<String, dynamic>),
  );

  final String status;
  final Map<String, ListSummary> lists;
}

class PinnedIncident {
  PinnedIncident({
    required this.candidateClipId,
    required this.startSec,
    required this.endSec,
    this.estStartAt,
    this.estEndAt,
    required this.clipUrl,
  });

  factory PinnedIncident.fromJson(Map<String, dynamic> j) => PinnedIncident(
    candidateClipId: j['candidate_clip_id'] as int,
    startSec: (j['start_sec'] as num).toDouble(),
    endSec: (j['end_sec'] as num).toDouble(),
    estStartAt: j['est_start_at'] as String?,
    estEndAt: j['est_end_at'] as String?,
    clipUrl: j['clip_url'] as String,
  );

  final int candidateClipId;
  final double startSec;
  final double endSec;
  final String? estStartAt;
  final String? estEndAt;
  final String clipUrl;
}

List<PinnedIncident> pinsFromJson(dynamic j) => (j as List)
    .map((e) => PinnedIncident.fromJson(e as Map<String, dynamic>))
    .toList();
