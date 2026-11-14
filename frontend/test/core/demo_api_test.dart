import 'package:flutter_test/flutter_test.dart';
import 'package:parking_lot_frontend/core/api/api_error.dart';
import 'package:parking_lot_frontend/core/api/demo_api.dart';

void main() {
  test('데모의 사건 이름·삭제는 계정마다 따로다 (D-239, D-240)', () async {
    final api = DemoApi();
    Future<Map<int, String?>> names() async => {for (final c in await api.cases()) c.id: c.caseName};

    await api.login('parking_admin', 'pw');
    final created = await api.createCase('victim05', caseName: 'B2 기둥 긁힘');
    expect(created.caseName, 'B2 기둥 긁힘');

    await api.login('victim05', 'pw');
    expect((await names())[created.id], matches(RegExp(r'^\d{4}-\d{2}-\d{2} 연결$'))); // 피해자 쪽 처음 이름
    // 수락 전 사건은 피해자가 고치거나 지울 수 없다
    await expectLater(api.renameCase(created.id, '내 사건'), throwsA(isA<ApiException>()));
    await api.acceptCase(created.id);
    await api.renameCase(created.id, '내 사건');
    expect((await names())[created.id], '내 사건');

    await api.login('parking_admin', 'pw');
    expect((await names())[created.id], 'B2 기둥 긁힘'); // 관리자 쪽 이름은 그대로
    final videos = (await api.videos()).where((v) => v.caseId == 1).length;
    expect(videos, greaterThan(0));
    await api.deleteCase(1);
    expect((await names()).containsKey(1), isFalse);
    expect((await api.videos()).where((v) => v.caseId == 1), isEmpty);
    await expectLater(api.deleteCase(1), throwsA(isA<ApiException>())); // 이미 지운 사건은 404

    await api.login('victim01', 'pw');
    expect((await names()).containsKey(1), isTrue); // 상대 계정에는 그대로 보인다
    expect((await api.videos()).where((v) => v.caseId == 1).length, videos);
  });
}
