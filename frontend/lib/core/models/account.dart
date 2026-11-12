// 1·3번(계정)과 21·22번(사건) 응답 (05장 5.3, 5.4).

/// 로그인한 계정. `role`은 `admin`(주차장 관리자) 또는 `victim`(피해자)이다 (D-204).
class Me {
  Me({required this.id, required this.loginId, required this.name, required this.role});

  factory Me.fromJson(Map<String, dynamic> j) => Me(
    id: j['id'] as int,
    loginId: j['login_id'] as String,
    name: j['name'] as String,
    role: j['role'] as String? ?? 'victim',
  );

  final int id;
  final String loginId;
  final String name;
  final String role;

  bool get isAdmin => role == 'admin';
}

/// 관리자가 피해자를 연결해 만든 사건 하나 (D-204). 21번 응답에는 `admin_name`이 없다.
class VideoCase {
  VideoCase({
    required this.id,
    this.caseName,
    this.adminName,
    required this.victimName,
    required this.createdAt,
    this.acceptedAt,
    this.pending = false,
  });

  factory VideoCase.fromJson(Map<String, dynamic> j) => VideoCase(
    id: j['id'] as int,
    caseName: j['case_name'] as String?,
    adminName: j['admin_name'] as String?,
    victimName: j['victim_name'] as String,
    createdAt: j['created_at'] as String,
    acceptedAt: j['accepted_at'] as String?,
    // 키가 없으면(지금 백엔드) 수락된 것으로 읽는다. 키가 있고 null일 때만 수락 전이다 (D-233)
    pending: j.containsKey('accepted_at') && j['accepted_at'] == null,
  );

  final int id;

  /// 지금 계정 쪽 사건 이름 (21·22번 `case_name`, D-237). 이름은 계정마다 따로이고, 피해자 쪽은 "YYYY-MM-DD 연결"로 시작한다.
  /// 이름 칼럼이 생기기 전에 만든 사건은 null이다 (D-240).
  final String? caseName;

  /// 화면에 보일 사건 이름. 비었으면 null이다.
  String? get name => (caseName?.trim().isEmpty ?? true) ? null : caseName!.trim();

  final String? adminName;
  final String victimName;
  final String createdAt;

  /// 피해자가 초대를 수락한 시각 (D-233 초안, 22번 `accepted_at`).
  final String? acceptedAt;

  /// 피해자가 아직 초대를 수락하지 않은 사건인지 (D-233).
  final bool pending;

  /// 화면 머리에 보일 상대 계정 ("피해자 홍길동", "관리자 주차장 관리자").
  String counterpart({required bool admin}) => admin ? '피해자 $victimName' : '관리자 ${adminName ?? ''}';
}
