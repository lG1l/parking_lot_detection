/// 백엔드 에러 응답 `{"error": {"code", "message"}}` (05장 5.1, D-38).
/// 화면은 `code`로만 경우를 나눈다. `message`는 개발자용이라 보이지 않는다.
class ApiException implements Exception {
  ApiException(this.status, this.code);

  final int status;
  final String code;

  @override
  String toString() => 'ApiException($status, $code)';
}

/// 네트워크가 끊겨 응답을 받지 못했을 때 쓰는 code.
const networkErrorCode = 'NETWORK_ERROR';

/// 07장 3.1 에러 문구. 화면별로 따로 정한 문구(업로드 링크, 파일)는 각 화면에 있다.
String errorMessage(String code) {
  switch (code) {
    case 'UNAUTHENTICATED':
      return '로그인이 필요합니다.';
    case 'LOGIN_FAILED':
      return '아이디 또는 비밀번호가 올바르지 않습니다.';
    case 'VIDEO_NOT_FOUND':
      return '영상을 찾을 수 없습니다.';
    case 'CLIP_NOT_FOUND':
      return '후보 영상을 찾을 수 없어 화면을 새로 고칩니다.';
    case 'INVALID_STATE':
    case 'NO_PINNED_INCIDENTS':
    case 'RETRY_NOT_ALLOWED':
    case 'RETRY_LIMIT_REACHED':
      return '상태가 변경되었습니다. 최신 화면으로 새로고침합니다.';
    case 'RAW_EXPIRED':
    case 'MASKED_EXPIRED':
      return '보관 기간(30일)이 지나 영상이 삭제되었습니다.';
    case 'VALIDATION_FAILED':
      return '입력값이 올바르지 않습니다. 다시 입력해 주세요.';
    case 'AGREEMENT_REQUIRED':
      return '위탁계약 동의가 확인되지 않습니다. 다시 동의해 주세요.';
    default:
      return '일시적인 시스템 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
  }
}

/// 9번을 다시 불러 화면을 새로 그려야 하는 code (07장 3.1).
bool needsStatusReload(String code) => const {
  'INVALID_STATE',
  'RAW_EXPIRED',
  'MASKED_EXPIRED',
  'RETRY_NOT_ALLOWED',
  'RETRY_LIMIT_REACHED',
}.contains(code);
