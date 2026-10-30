import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/theme.dart';
import '../../core/api/api.dart';
import '../../core/api/api_error.dart';
import '../../core/browser/browser.dart';
import '../../core/constants.dart';
import '../../core/format.dart';
import '../../core/models/analysis.dart';
import '../../core/widgets/common.dart';
import '../video_status/status_rules.dart';
import '../video_status/video_status_page.dart';
import 'geometry.dart';
import 'still_canvas.dart';

/// 입력 단계 (07장 2.6, 순서는 D-98).
enum InputStep { vehicle, visibility, damage, corners, edges, extras, confirm }

/// 사진 고르기 검사 (D-83). 통과하면 null.
String? checkPhoto(String name, int size) {
  if (!photoExtensions.contains(fileExtension(name))) return 'jpg, png, heic 사진만 올릴 수 있습니다.';
  if (size > maxPhotoBytes) return '사진은 20MB까지 올릴 수 있습니다.';
  return null;
}

/// 11번 요청 본문 (05장 5.7, schema_version 5).
Map<String, Object> inputBody({
  required int stillFrameId,
  required int detId,
  required bool visible,
  required Box damageBox,
  required List<Pt> corners,
  required List<int> edges,
  String? description,
  String? photoKey,
}) => {
  'still_frame_id': stillFrameId,
  'schema_version': 5,
  'vehicle': {'det_id': detId},
  'damage': {
    'visible': visible,
    'damage_bbox': damageBox,
    'floor_corners': [
      for (final c in corners) [c.x, c.y],
    ],
    'damage_edges': edges,
    if (description != null && description.isNotEmpty) 'description': description,
    'photo_key': ?photoKey,
  },
};

enum _PhotoFailChoice { retry, withoutPhoto }

/// 2.6 차량 선택·파손 부위 입력. 단계 사이에는 서버를 부르지 않고 마지막 [저장]에서만 부른다 (D-36).
class DamageInputPage extends ConsumerStatefulWidget {
  const DamageInputPage({super.key, required this.videoId});

  final String videoId;

  @override
  ConsumerState<DamageInputPage> createState() => _DamageInputPageState();
}

class _DamageInputPageState extends ConsumerState<DamageInputPage> {
  int get _id => int.parse(widget.videoId);
  Api get _api => ref.read(apiProvider);

  String? _viewExpiresAt;
  String? _filename;
  Still? _still;
  Size? _natural;
  DateTime? _lastStillReload;
  bool _reupload = false;
  bool _stillFailed = false;

  InputStep _step = InputStep.vehicle;
  int? _detId;
  int? _hoverDetId;
  bool? _visible;
  Box? _damage;
  Pt? _dragStart;
  Box? _dragBox;
  List<Pt> _corners = [];
  List<int> _edges = [];
  String? _stepError;
  PickedFile? _photo;
  String? _photoError;
  final _description = TextEditingController();
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _open();
  }

  @override
  void dispose() {
    _description.dispose();
    super.dispose();
  }

  Box? get _vehicleBox {
    final still = _still;
    if (still == null || _detId == null) return null;
    return still.detections.firstWhere((d) => d.detId == _detId).bbox;
  }

  bool get _entered =>
      _detId != null || _visible != null || _corners.isNotEmpty || _photo != null || _description.text.isNotEmpty;

  /// 9번으로 이 화면이 맞는지 본 뒤 10번을 한 번 부른다.
  Future<void> _open() async {
    try {
      final d = await _api.video(_id); // 9
      if (!mounted) return;
      if (selectScreen(d) != StatusScreen.input) {
        goStatus(context, _id); // 입력을 마쳤으면 입력 화면을 열지 않는다 (D-66)
        return;
      }
      _viewExpiresAt = d.viewExpiresAt;
      _filename = d.originalFilename;
      await _loadStill();
    } catch (e) {
      _onError(e);
    }
  }

  Future<void> _loadStill() async {
    _lastStillReload = DateTime.now();
    final still = await _api.still(_id); // 10
    final natural = await ref.read(browserProvider).imageNaturalSize(still.imageUrl);
    if (!mounted) return;
    setState(() {
      _still = still;
      _natural ??= natural;
      _stillFailed = _natural == null;
      _reupload = still.detections.isEmpty; // 탐지 0건이면 재업로드 안내 (D-65)
    });
  }

  /// 이미지 URL이 만료됐으면 10번을 다시 불러 새 URL을 받는다 (D-41). 입력한 값은 그대로다.
  void _onImageError() {
    final last = _lastStillReload;
    if (last != null && DateTime.now().difference(last) < const Duration(seconds: 10)) return;
    _loadStill().catchError(_onError);
  }

  void _onError(Object e) {
    if (!mounted) return;
    if (handleCommonError(context, e)) return;
    final code = errorCode(e);
    if (needsStatusReload(code)) goStatus(context, _id, expired: isExpiredCode(code));
  }

  void _setError(String? message) => setState(() => _stepError = message);

  void _go(InputStep step) => setState(() {
    _step = step;
    _stepError = null;
  });

  // ① 차량 고르기
  void _tapVehicle(double x, double y) {
    final picked = pickDetection(_still!.detections, x, y, _detId);
    if (picked == null) return;
    setState(() {
      _detId = picked;
      final box = _vehicleBox!;
      if (_damage != null && !boxInside(_damage!, box)) _damage = null;
    });
  }

  void _hoverVehicle(double x, double y) {
    final hits = _still!.detections.where((d) => boxContainsPoint(d.bbox, x, y)).toList()
      ..sort(
        (a, b) => ((a.bbox[2] - a.bbox[0]) * (a.bbox[3] - a.bbox[1])).compareTo(
          (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]),
        ),
      );
    final id = hits.isEmpty ? null : hits.first.detId;
    if (id != _hoverDetId) setState(() => _hoverDetId = id);
  }

  // ③ 파손 부위 드래그
  void _dragEnd() {
    final box = _dragBox;
    setState(() {
      _dragStart = null;
      _dragBox = null;
    });
    if (box == null) return;
    if (!boxInside(box, _vehicleBox!)) {
      setState(() => _damage = null);
      _setError(_visible == true ? '파손 부위가 차량을 벗어났습니다. 다시 그려주세요.' : '파손 위치가 차량을 벗어났습니다. 다시 그려주세요.');
      return;
    }
    setState(() => _damage = box);
    _setError(null);
  }

  // ④ 바닥 네 모서리
  void _tapCorner(double x, double y) {
    if (_corners.length >= 4) return;
    final p = toImagePoint(x, y, 1, _natural!.width.round(), _natural!.height.round());
    if (_corners.contains(p)) return; // 같은 점을 두 번 찍지 못한다
    final next = [..._corners, p];
    if (next.length == 4 && isTwisted(next)) {
      setState(() => _corners = []);
      _setError('모서리를 차 둘레를 따라 차례로 찍어주세요.');
      return;
    }
    setState(() {
      _corners = next;
      _edges = [];
    });
    _setError(null);
  }

  // ⑤ 파손 변
  void _tapEdge(int edge) {
    final r = toggleEdge(_edges, edge);
    setState(() => _edges = r.edges);
    _setError(r.blocked ? '이웃한 두 변만 고를 수 있습니다.' : null);
  }

  // ⑥ 사진
  Future<void> _pickPhoto() async {
    final file = await ref.read(browserProvider).pickFile(photoExtensions);
    if (file == null || !mounted) return;
    final error = checkPhoto(file.name, file.size);
    setState(() {
      _photoError = error;
      _photo = error == null ? file : _photo;
    });
  }

  /// 사진이 있으면 18번 → S3 PUT, 그다음 11번 (D-83).
  Future<void> _save() async {
    if (_saving) return;
    // 저장하면 고칠 수 없으므로 한 번 더 묻는다 (D-190)
    if (!await confirm(
      context,
      '저장한 뒤에는 입력을 고칠 수 없고, 바로 영상 분석을 시작합니다.',
      title: '입력을 저장할까요?',
      okLabel: '저장',
    )) {
      return;
    }
    if (!mounted || _saving) return;
    setState(() => _saving = true); // 버튼을 바로 막는다
    // 백엔드 연결 필요: 18번 사진 URL 발급 → S3 PUT (사진이 있을 때) → 11번 입력 저장
    await backendNotice(context, ref, '저장');
    try {
      String? photoKey;
      final photo = _photo;
      if (photo != null) {
        photoKey = await _uploadPhoto(photo);
        if (photoKey == '') {
          setState(() => _saving = false); // 창을 닫음
          return;
        }
      }
      final text = _description.text.trim();
      await _api.saveInput(
        _id,
        inputBody(
          stillFrameId: _still!.stillFrameId,
          detId: _detId!,
          visible: _visible!,
          damageBox: _damage!,
          corners: _corners,
          edges: _edges,
          description: text.isEmpty ? null : text,
          photoKey: photoKey,
        ),
      ); // 11
      if (mounted) goStatus(context, _id); // 2단계 대기 화면
    } catch (e) {
      if (!mounted) return;
      setState(() => _saving = false);
      _onError(e);
      if (errorCode(e) == 'VALIDATION_FAILED') _go(InputStep.vehicle);
    }
  }

  /// 올린 사진의 키. 사진 없이 저장하면 null, 사용자가 창을 닫으면 ''.
  Future<String?> _uploadPhoto(PickedFile photo) async {
    while (true) {
      // 18번 에러(RAW_EXPIRED·INVALID_STATE 등)는 창을 띄우지 않고 _save의 catch로 간다
      final presign = await _api.presignPhoto(_id, filename: photo.name, sizeBytes: photo.size);
      final status = await ref.read(browserProvider).putFile(presign.uploadUrl, photo);
      if (status == 200) return presign.photoKey;
      if (!mounted) return '';
      // S3 PUT 실패나 네트워크 오류일 때만 고르게 한다 (D-92)
      final choice = await showDialog<_PhotoFailChoice>(
        context: context,
        builder: (context) => AlertDialog(
          content: const Text('사진을 올리지 못했습니다.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, _PhotoFailChoice.withoutPhoto),
              child: const Text('사진 없이 저장'),
            ),
            FilledButton(onPressed: () => Navigator.pop(context, _PhotoFailChoice.retry), child: const Text('다시 올리기')),
          ],
        ),
      );
      if (choice == null) return '';
      if (choice == _PhotoFailChoice.withoutPhoto) return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    return PageFrame(
      canLeave: _confirmLeave,
      title: _reupload || _stillFailed || _still == null ? (_filename ?? '차량·파손 부위 입력') : null,
      child: _reupload
          ? _reuploadView(context)
          : _stillFailed
          ? StateCard(
              icon: Icons.error_outline,
              iconColor: failColor,
              title: '정지 장면을 불러오지 못했습니다.',
              actions: [
                FilledButton(
                  style: largeButtonStyle,
                  onPressed: () => _loadStill().catchError(_onError),
                  child: const Text('다시 불러오기'),
                ),
              ],
            )
          : (_still == null || _natural == null)
          ? const Center(child: CircularProgressIndicator())
          : _stepView(context),
    );
  }

  /// 상단 바로 떠날 때 저장하지 않은 입력이 있으면 묻는다.
  Future<bool> _confirmLeave() async {
    if (!_entered) return true;
    return confirm(context, '저장하지 않은 입력은 사라집니다. 이 화면을 떠날까요?', okLabel: '떠나기', cancelLabel: '계속 입력');
  }

  Widget _reuploadView(BuildContext context) {
    return StateCard(
      icon: Icons.directions_car_outlined,
      messages: const [
        '이 장면에서 본인 차량을 찾지 못했습니다. 관리자에게 차가 이미 주차된 뒤의 장면부터 영상을 다시 잘라 달라고 '
            '요청한 뒤, 새 업로드 링크를 발급해 전달해 주세요.',
      ],
      actions: [
        if (_still!.detections.isNotEmpty)
          OutlinedButton(onPressed: () => setState(() => _reupload = false), child: const Text('차량 고르기로 돌아가기')),
        FilledButton(
          style: largeButtonStyle,
          onPressed: () => context.go('/videos/upload-link'),
          child: const Text('업로드 링크 받기'),
        ),
      ],
    );
  }

  /// 단계 제목과 보조 안내 (07장 2.6 문구에서 번호를 뺐다. 번호는 단계 표시줄에 있다).
  (String, String?) get _instruction => switch (_step) {
    InputStep.vehicle => ('본인 차량을 눌러 선택해주세요', null),
    InputStep.visibility => ('파손 부위가 이 장면에 보이나요?', null),
    InputStep.damage =>
      _visible == true ? ('고른 차량 안에서 파손 부위를 드래그해 주세요', null) : ('보이지 않는 파손이 있을 위치를 작은 사각형으로 드래그해주세요', null),
    InputStep.corners => ('차가 바닥에 닿는 네 모서리를 차례로 눌러주세요', '가려진 모서리는 짐작해서 찍어도 됩니다.'),
    InputStep.edges => ('파손이 있는 쪽 변을 눌러주세요', '모서리 파손이면 이웃한 두 변을 누르세요.'),
    InputStep.extras => ('파손 사진과 설명을 남겨주세요', '선택 사항입니다. 비워 두고 다음으로 넘어가도 됩니다.'),
    InputStep.confirm => ('입력한 내용을 확인해주세요', '저장한 뒤에는 고칠 수 없습니다.'),
  };

  StillOverlay get _overlay {
    final s = _step.index;
    return StillOverlay(
      detections: _step == InputStep.vehicle ? _still!.detections : const [],
      hoveredDetId: _step == InputStep.vehicle ? _hoverDetId : null,
      selectedBox: _vehicleBox,
      damageBox: s >= InputStep.damage.index ? (_dragBox ?? _damage) : null,
      corners: s >= InputStep.corners.index ? _corners : const [],
      edges: s >= InputStep.edges.index ? _edges : const [],
      edgesClickable: _step == InputStep.edges,
    );
  }

  Widget _canvas() {
    final drag = _step == InputStep.damage;
    return StillCanvas(
      imageUrl: _still!.imageUrl,
      natural: _natural!,
      overlay: _overlay,
      onImageError: _onImageError,
      onTap: switch (_step) {
        InputStep.vehicle => _tapVehicle,
        InputStep.corners => _tapCorner,
        _ => null,
      },
      onHover: _step == InputStep.vehicle ? _hoverVehicle : null,
      onDragStart: drag ? (p) => setState(() => _dragStart = p) : null,
      onDragUpdate: drag
          ? (p) {
              final start = _dragStart;
              if (start != null) setState(() => _dragBox = boxFromDrag(start, p));
            }
          : null,
      onDragEnd: drag ? _dragEnd : null,
      onEdgeTap: _step == InputStep.edges ? _tapEdge : null,
    );
  }

  /// 단계 표시줄 · 파일 이름 · 단계 제목, 그 아래 왼쪽 정지 장면과 오른쪽 단계 패널 (캔버스 2.6).
  Widget _stepView(BuildContext context) {
    final (title, hint) = _instruction;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _StepBar(current: _step),
        const SizedBox(height: 20),
        if (_filename != null)
          Text(
            _filename!,
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: subColor),
          ),
        const SizedBox(height: 10),
        Text(title, style: pageTitleStyle),
        const SizedBox(height: 20),
        LayoutBuilder(
          builder: (context, c) => c.maxWidth >= 900
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // 열람기한은 정지 장면 바로 아래. 오른쪽 칸이 길어져도(사진·설명 단계) 같은 자리다
                    Expanded(
                      flex: 760,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [_canvas(), const SizedBox(height: 16), SmallText(viewExpiresText(_viewExpiresAt))],
                      ),
                    ),
                    const SizedBox(width: 28),
                    Expanded(
                      flex: 412,
                      // 단계 보조 안내는 오른쪽 칸 맨 위(카드 바로 위) 빈 자리에 띄운다. 정지 장면과 카드 윗선이 맞는다 (D-190)
                      child: Stack(
                        clipBehavior: Clip.none,
                        children: [
                          _panel(context, hintInside: false),
                          if (hint != null)
                            Positioned(
                              left: 0,
                              right: 0,
                              top: 0,
                              // 자기 높이만큼 위로 올려 카드 바로 위에 붙인다
                              child: FractionalTranslation(
                                translation: const Offset(0, -1),
                                child: Padding(padding: const EdgeInsets.only(bottom: 4), child: _hintText(hint)),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _canvas(),
                    const SizedBox(height: 20),
                    _panel(context, hintInside: true),
                    const SizedBox(height: 16),
                    SmallText(viewExpiresText(_viewExpiresAt)),
                  ],
                ),
        ),
      ],
    );
  }

  /// 오른쪽 패널: 오류 · 단계별 카드 · 이전/다음 버튼.
  /// 단계 보조 안내 글자. 확인 단계("저장한 뒤에는 고칠 수 없습니다.")만 빨갛고 굵게.
  Widget _hintText(String hint) => _step == InputStep.confirm
      ? Text(
          hint,
          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: failColor),
        )
      : Text(hint, style: const TextStyle(fontSize: 14, color: noteColor));

  /// [hintInside]: 좁은 화면이라 보조 안내를 패널 안 카드 위에 둔다.
  Widget _panel(BuildContext context, {required bool hintInside}) {
    final section = _section(context);
    final (_, hint) = _instruction;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (hintInside && hint != null) ...[_hintText(hint), const SizedBox(height: 8)],
        if (_stepError != null) ...[
          Text(_stepError!, style: const TextStyle(fontSize: 14, color: failColor)),
          const SizedBox(height: 18),
        ],
        for (final card in section) ...[card, const SizedBox(height: 18)],
        _buttons(),
      ],
    );
  }

  /// 단계별 카드. 없으면 빈 목록.
  List<Widget> _section(BuildContext context) {
    Widget card(List<Widget> children) => PageCard(
      padding: const EdgeInsets.all(20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, spacing: 14, children: children),
    );
    Text status(String text) => Text(text, style: const TextStyle(fontSize: 15, color: subColor));
    return switch (_step) {
      InputStep.vehicle => const [],
      InputStep.visibility => [
        card([
          const SectionTitle('파손 부위가 이 장면에 보이나요?'),
          Row(
            spacing: 10,
            children: [
              // 고르기만 하고 [다음]으로 넘어간다. 고른 쪽은 진한 버튼 (D-190)
              for (final (value, label) in const [(true, '보임'), (false, '안 보임')])
                Expanded(
                  child: Semantics(
                    selected: _visible == value,
                    child: _visible == value
                        ? FilledButton(onPressed: () {}, child: Text(label))
                        : OutlinedButton(onPressed: () => setState(() => _visible = value), child: Text(label)),
                  ),
                ),
            ],
          ),
        ]),
      ],
      InputStep.damage => [
        card([
          const SectionTitle('파손 부위'),
          status(_damage == null ? '고른 차량 안을 드래그해 사각형을 그려 주세요.' : '빨간 사각형 1개를 그렸습니다.'),
          OutlinedButton(
            onPressed: _damage == null ? null : () => setState(() => _damage = null),
            child: const Text('다시 그리기'),
          ),
        ]),
      ],
      InputStep.corners => [
        card([
          const SectionTitle('바닥 모서리'),
          status('4개 중 ${_corners.length}개를 찍었습니다.'),
          OutlinedButton(
            onPressed: () => setState(() {
              _corners = [];
              _edges = [];
              _stepError = null;
            }),
            child: const Text('다시 찍기'),
          ),
        ]),
      ],
      InputStep.edges => [
        card([
          const SectionTitle('고른 파손 변'),
          status('${_edges.length}개를 골랐습니다.'),
          OutlinedButton(
            onPressed: _edges.isEmpty ? null : () => setState(() => _edges = []),
            child: const Text('다시 고르기'),
          ),
        ]),
      ],
      InputStep.extras => _extras(context),
      InputStep.confirm => [
        card([const SectionTitle('입력 내용'), _summary()]),
      ],
    };
  }

  List<Widget> _extras(BuildContext context) {
    final photo = _photo;
    return [
      PageCard(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          spacing: 10,
          children: [
            // 제목 오른쪽에 고른 사진 이름, 그 아래 [사진 바꾸기]·[사진 빼기]를 나란히 (D-190)
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              spacing: 12,
              children: [
                const SectionTitle('파손 사진'),
                if (photo != null)
                  Expanded(
                    child: Text(
                      photo.name,
                      style: const TextStyle(fontSize: 14, color: subColor),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
            ),
            Wrap(
              spacing: 10,
              runSpacing: 8,
              children: [
                OutlinedButton(onPressed: _pickPhoto, child: Text(photo == null ? '사진 선택' : '사진 바꾸기')),
                if (photo != null)
                  OutlinedButton(onPressed: () => setState(() => _photo = null), child: const Text('사진 빼기')),
              ],
            ),
            const SmallText('jpg·png·heic · 최대 20MB'),
            if (_photoError != null) Text(_photoError!, style: const TextStyle(fontSize: 14, color: failColor)),
          ],
        ),
      ),
      PageCard(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 10,
          children: [
            const SectionTitle('파손 설명'),
            TextField(
              controller: _description,
              maxLength: maxDescriptionLength,
              maxLines: 3,
              decoration: const InputDecoration(hintText: '예: 조수석 뒷문 아래가 긁혔어요'),
            ),
          ],
        ),
      ),
    ];
  }

  /// 저장 전 확인표 (이름 · 값 두 칸).
  Widget _summary() {
    final photo = _photo;
    final text = _description.text.trim();
    final rows = [
      ('선택한 차량', '노란 사각형'),
      ('파손 보임', _visible == true ? '보임' : '안 보임'),
      ('파손 부위', '빨간 사각형'),
      ('바닥 모서리', '${_corners.length}개'),
      ('파손 변', '${_edges.length}개'),
      ('사진', photo == null ? '없음' : photo.name),
      ('설명', text.isEmpty ? '없음' : text),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final (i, (name, value)) in rows.indexed)
          Container(
            padding: const EdgeInsets.symmetric(vertical: 8),
            decoration: BoxDecoration(
              border: i == 0 ? null : const Border(top: BorderSide(color: lineColor)),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 96,
                  child: Text(name, style: const TextStyle(fontSize: 14, color: subColor)),
                ),
                Expanded(child: Text(value, style: const TextStyle(fontSize: 14))),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buttons() {
    Widget prev(InputStep to) => Expanded(
      child: OutlinedButton(onPressed: () => _go(to), child: const Text('이전 단계')),
    );
    Widget next(InputStep to, {bool enabled = true}) => Expanded(
      child: FilledButton(onPressed: enabled ? () => _go(to) : null, child: const Text('다음')),
    );
    return switch (_step) {
      InputStep.vehicle => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 18,
        children: [
          Row(children: [next(InputStep.visibility, enabled: _detId != null)]),
          OutlinedButton(onPressed: () => setState(() => _reupload = true), child: const Text('내 차가 목록에 없습니다')),
        ],
      ),
      InputStep.confirm => Row(
        spacing: 12,
        children: [
          Expanded(
            child: OutlinedButton(onPressed: _saving ? null : () => _go(InputStep.extras), child: const Text('이전 단계')),
          ),
          Expanded(
            child: FilledButton(onPressed: _saving ? null : _save, child: const Text('저장')),
          ),
        ],
      ),
      _ => Row(
        spacing: 12,
        children: switch (_step) {
          InputStep.visibility => [prev(InputStep.vehicle), next(InputStep.damage, enabled: _visible != null)],
          InputStep.damage => [prev(InputStep.visibility), next(InputStep.corners, enabled: _damage != null)],
          InputStep.corners => [prev(InputStep.damage), next(InputStep.edges, enabled: _corners.length == 4)],
          InputStep.edges => [prev(InputStep.corners), next(InputStep.extras, enabled: _edges.isNotEmpty)],
          _ => [prev(InputStep.edges), next(InputStep.confirm)],
        },
      ),
    };
  }
}

/// 입력 일곱 단계 표시줄. 지금 단계만 남색 동그라미 (캔버스 2.6).
class _StepBar extends StatelessWidget {
  const _StepBar({required this.current});

  final InputStep current;

  static const _labels = ['차량 고르기', '파손이 보이나요?', '파손 부위 드래그', '바닥 네 모서리', '파손 변 고르기', '사진·설명 (선택)', '확인 후 저장'];

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '입력 단계 ${current.index + 1} / ${_labels.length}',
      child: PageCard(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
        child: Wrap(
          spacing: 32,
          runSpacing: 12,
          children: [
            for (final (i, label) in _labels.indexed)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 24,
                    height: 24,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: i == current.index ? pointColor : null,
                      border: Border.all(color: i == current.index ? pointColor : const Color(0xFF8F8F8B), width: 1.5),
                    ),
                    child: Text(
                      '${i + 1}',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: i == current.index ? offWhiteColor : noteColor,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: i == current.index ? FontWeight.w600 : FontWeight.w400,
                      color: i == current.index ? inkColor : noteColor,
                    ),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
