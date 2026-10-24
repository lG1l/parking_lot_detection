// 01장 1.6 주요 상수 중 화면이 쓰는 값. 백엔드 상수와 같아야 한다.

/// 9번 주기 조회 간격 (D-138, D-19).
const pollInterval = Duration(seconds: 5);

/// 관리자 업로드 한도 5GB (D-22). 백엔드 `MAX_UPLOAD_BYTES`와 같다.
const maxUploadBytes = 5 * 1024 * 1024 * 1024;

/// 관리자 업로드 확장자 (D-43).
const uploadExtensions = ['mp4', 'avi', 'mkv', 'mov'];

/// 업로드 남은 시간이 이 값 이하가 되면 16번을 1회 부른다 (D-62).
const warmupThreshold = Duration(minutes: 3);

/// 파손 사진 한도 20MB와 확장자 (D-83).
const maxPhotoBytes = 20 * 1024 * 1024;
const photoExtensions = ['jpg', 'jpeg', 'png', 'heic'];

/// 파손 설명 최대 글자 수 (01장 1.6).
const maxDescriptionLength = 500;

/// 사용자 재시도 최대 횟수 (D-112). 문구에만 쓰고 남은 횟수는 서버 값을 쓴다.
const maxUserRetries = 3;

/// 파일 이름의 마지막 `.` 뒤를 소문자로. 없으면 빈 문자열.
String fileExtension(String filename) {
  final dot = filename.lastIndexOf('.');
  if (dot < 0 || dot == filename.length - 1) return '';
  return filename.substring(dot + 1).toLowerCase();
}
