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
  VideoCase({required this.id, this.adminName, required this.victimName, required this.createdAt});

  factory VideoCase.fromJson(Map<String, dynamic> j) => VideoCase(
    id: j['id'] as int,
    adminName: j['admin_name'] as String?,
    victimName: j['victim_name'] as String,
    createdAt: j['created_at'] as String,
  );

  final int id;
  final String? adminName;
  final String victimName;
  final String createdAt;

  /// 화면 머리에 보일 상대 계정 ("피해자 홍길동", "관리자 주차장 관리자").
  String counterpart({required bool admin}) => admin ? '피해자 $victimName' : '관리자 ${adminName ?? ''}';
}
