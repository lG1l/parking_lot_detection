import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
      ..sort((a, b) => ((a.bbox[2] - a.bbox[0]) * (a.bbox[3] - a.bbox[1]))
          .compareTo((b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1])));
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
      _setError(_visible == true
          ? '파손 부위가 차량을 벗어났습니다. 다시 그려주세요.'
          : '파손 위치가 차량을 벗어났습니다. 다시 그려주세요.');
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

  Future<void> _backToList() async {
    if (_entered &&
        !await confirm(context, '저장하지 않은 입력은 사라집니다. 목록으로 갈까요?',
            okLabel: '목록으로', cancelLabel: '계속 입력')) {
      return;
    }
    if (mounted) context.go('/videos');
  }

  /// 사진이 있으면 18번 → S3 PUT, 그다음 11번 (D-83).
  Future<void> _save() async {
    if (_saving) return;
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
            FilledButton(
              onPressed: () => Navigator.pop(context, _PhotoFailChoice.retry),
              child: const Text('다시 올리기'),
            ),
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
      title: '차량·파손 부위 입력',
      maxWidth: 1100,
      actions: [BackToListButton(onPressed: _backToList)],
      child: _reupload
          ? _reuploadView(context)
          : _stillFailed
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Notice('정지 장면을 불러오지 못했습니다.', icon: Icons.error_outline),
                const SizedBox(height: 12),
                FilledButton(
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

  Widget _reuploadView(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Notice(
          '이 장면에서 본인 차량을 찾지 못했습니다. 관리자에게 차가 이미 주차된 뒤의 장면부터 영상을 다시 잘라 달라고 '
          '요청한 뒤, 새 업로드 링크를 발급해 전달해 주세요.',
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 12,
          children: [
            FilledButton(
              onPressed: () => context.go('/videos/upload-link'),
              child: const Text('업로드 링크 받기'),
            ),
            if (_still!.detections.isNotEmpty)
              TextButton(
                onPressed: () => setState(() => _reupload = false),
                child: const Text('차량 고르기로 돌아가기'),
              ),
          ],
        ),
      ],
    );
  }

  String get _instruction => switch (_step) {
    InputStep.vehicle => '① 본인 차량을 눌러 선택해주세요',
    InputStep.visibility => '② 파손 부위가 이 장면에 보이나요?',
    InputStep.damage => _visible == true
        ? '③ 파손 부위를 드래그해주세요'
        : '③ 보이지 않는 파손이 있을 위치를 작은 사각형으로 드래그해주세요',
    InputStep.corners => '④ 내 차 바퀴 아래, 차가 바닥에 닿는 네 모서리를 차 둘레를 따라 차례로 눌러주세요. '
        '가려진 모서리는 짐작해서 찍어도 됩니다.',
    InputStep.edges => '⑤ 파손이 있는 쪽 변을 눌러주세요. 모서리 파손이면 이웃한 두 변을 누르세요.',
    InputStep.extras => '⑥ 파손 사진과 설명이 있으면 분석에 도움이 됩니다. 없어도 저장할 수 있습니다.',
    InputStep.confirm => '⑦ 이대로 분석을 시작합니다. 저장한 뒤에는 고칠 수 없습니다.',
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

  Widget _stepView(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(_instruction, style: text.titleMedium),
        if (_stepError != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_stepError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
        const SizedBox(height: 12),
        if (_step != InputStep.extras) _canvas(),
        if (_step == InputStep.extras) _extras(context),
        if (_step == InputStep.confirm) _summary(context),
        const SizedBox(height: 16),
        _buttons(),
        const SizedBox(height: 16),
        SmallText(viewExpiresText(_viewExpiresAt)),
      ],
    );
  }

  Widget _extras(BuildContext context) {
    final photo = _photo;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            OutlinedButton.icon(
              onPressed: _pickPhoto,
              icon: const Icon(Icons.photo_outlined),
              label: Text(photo == null ? '사진 선택 (선택)' : '사진 바꾸기'),
            ),
            if (photo != null) ...[
              const SizedBox(width: 12),
              Expanded(child: Text(photo.name)),
              TextButton(onPressed: () => setState(() => _photo = null), child: const Text('사진 빼기')),
            ],
          ],
        ),
        if (_photoError != null)
          Text(_photoError!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        if (photo != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Image.network(photo.objectUrl, height: 200, fit: BoxFit.contain),
          ),
        const SizedBox(height: 16),
        TextField(
          controller: _description,
          maxLength: maxDescriptionLength,
          maxLines: 4,
          decoration: const InputDecoration(labelText: '파손 설명 (선택)', border: OutlineInputBorder()),
        ),
      ],
    );
  }

  Widget _summary(BuildContext context) {
    final photo = _photo;
    final text = _description.text.trim();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('탐지 상황: ${_visible == true ? '파손 부위가 보임' : '파손 부위가 보이지 않음'}'),
          Text('고른 파손 변: ${_edges.map((e) => '${e + 1}번 변').join(', ')}'),
          Text('설명: ${text.isEmpty ? '없음' : text}'),
          Text('사진: ${photo == null ? '없음' : photo.name}'),
          if (photo != null) Image.network(photo.objectUrl, height: 120, fit: BoxFit.contain),
        ],
      ),
    );
  }

  Widget _buttons() {
    Widget prev(InputStep to) => OutlinedButton(onPressed: () => _go(to), child: const Text('이전 단계'));
    Widget next(InputStep to, {bool enabled = true}) =>
        FilledButton(onPressed: enabled ? () => _go(to) : null, child: const Text('다음'));
    final children = switch (_step) {
      InputStep.vehicle => [
        OutlinedButton(
          onPressed: () => setState(() => _reupload = true),
          child: const Text('내 차가 목록에 없습니다'),
        ),
        next(InputStep.visibility, enabled: _detId != null),
      ],
      InputStep.visibility => [
        prev(InputStep.vehicle),
        FilledButton(
          onPressed: () {
            setState(() => _visible = true);
            _go(InputStep.damage);
          },
          child: const Text('보임'),
        ),
        FilledButton(
          onPressed: () {
            setState(() => _visible = false);
            _go(InputStep.damage);
          },
          child: const Text('안 보임'),
        ),
      ],
      InputStep.damage => [prev(InputStep.visibility), next(InputStep.corners, enabled: _damage != null)],
      InputStep.corners => [
        prev(InputStep.damage),
        OutlinedButton(
          onPressed: () => setState(() {
            _corners = [];
            _edges = [];
            _stepError = null;
          }),
          child: const Text('다시 찍기'),
        ),
        next(InputStep.edges, enabled: _corners.length == 4),
      ],
      InputStep.edges => [prev(InputStep.corners), next(InputStep.extras, enabled: _edges.isNotEmpty)],
      InputStep.extras => [prev(InputStep.edges), next(InputStep.confirm)],
      InputStep.confirm => [
        OutlinedButton(onPressed: _saving ? null : () => _go(InputStep.vehicle), child: const Text('취소')),
        FilledButton(onPressed: _saving ? null : _save, child: const Text('저장')),
      ],
    };
    return Wrap(spacing: 12, runSpacing: 8, children: children);
  }
}
