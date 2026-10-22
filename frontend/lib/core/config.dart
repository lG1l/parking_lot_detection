/// 백엔드에 실제로 연결할지.
///
/// - false(기본): 백엔드 없이 예시 데이터로 화면만 본다. API를 부르지 않는다 ([DemoApi]).
///   백엔드로 보내야 하는 버튼은 "눌렀다" 팝업을 한 번 띄운 뒤 성공한 것처럼 다음 화면으로 간다.
/// - true: 실제 API를 부른다. `flutter run -d chrome --dart-define=USE_BACKEND=true`
///
/// 백엔드에 붙일 때 고칠 곳은 코드에서 "백엔드 연결 필요"로 찾는다.
const useBackend = bool.fromEnvironment('USE_BACKEND');
