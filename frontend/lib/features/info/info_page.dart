import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';

/// 사용법 한 단계: 카드 제목 · 설명 · 아래 한 줄 메모.
typedef _Step = ({String title, String text, String note});

// 사용법 문구의 원본은 07장 2.13이다. 화면 흐름이 바뀌면 함께 고친다 (D-235).
const List<_Step> _adminSteps = [
  (
    title: '사건 연결',
    text: '[사건 관계자 연결]에서 피해자 계정 아이디를 입력해 사건에 초대합니다.',
    note: "수락 전에는 목록에 '수락 대기 중'",
  ),
  (
    title: '영상 업로드',
    text: '위탁계약에 동의하고 CCTV 영상을 올립니다. 피해자가 초대를 수락하기 전에도 올릴 수 있습니다.',
    note: '업로드가 끝나면 영상 상태 화면으로',
  ),
  (
    title: '진행도 확인',
    text: '[사건 목록]에서 영상을 눌러 진행도를 봅니다. 피해자가 차량과 파손 부위를 입력하면 분석이 시작됩니다.',
    note: "입력 전에는 '사전 입력 필요'",
  ),
  (
    title: '후보 확인',
    text: '분석이 끝나면 관리·감독 안내에 동의한 뒤, 피해자와 함께 후보 영상을 확인하고 찾은 장면을 [찾음]으로 고정합니다.',
    note: '열람은 관리·감독 동의 후에만 가능',
  ),
  (
    title: '결과 확인',
    text: '확인을 끝내면 결과 화면에서 고정한 장면의 원본 영상 기준 시간을 봅니다.',
    note: '원본 기준 시간과 추정 실제 시각',
  ),
];

const List<_Step> _victimSteps = [
  (title: '초대 수락', text: '[채팅]에서 관리자의 사건 초대를 [수락]합니다.', note: '수락해야 사건이 목록에 보입니다'),
  (title: '진행도 확인', text: '[사건 목록]에서 영상을 눌러 진행도를 봅니다.', note: "준비되면 '사전 입력 필요'"),
  (title: '차량·파손 입력', text: '영상이 준비되면 내 차량과 파손 부위를 입력합니다.', note: '빨간 모서리로 파손 부위 표시'),
  (title: '후보 확인', text: '분석이 끝나면 관리자 화면에서 관리자와 함께 후보 영상을 확인합니다.', note: '후보 영상은 관리자 화면에서'),
  (
    title: '시간 확인',
    text: '확인이 끝나면 [사건 목록]에서 고정한 사건 지점의 시간을 다시 볼 수 있습니다. 경찰에 신고할 때 전달하세요.',
    note: '열람기한까지 다시 볼 수 있습니다',
  ),
];

typedef _Tip = ({String title, String text});

const List<_Tip> _features = [
  (title: '개인정보 마스킹', text: '사람 얼굴과 번호판이 가려진 장면만 분석에 사용합니다.'),
  (title: '후보 구간 선별', text: '차량 이동과 파손 입력을 바탕으로 점수가 매겨진 후보를 보여 줍니다.'),
  (title: '관리자 최종 확인', text: '후보는 관리자가 하나씩 확인하고 결과를 저장합니다.'),
];

const List<_Tip> _adminTips = [
  (title: '관리·감독 안내', text: '후보 화면에 들어갈 때마다 동의 후 열람합니다.'),
  (title: '열람 기한', text: '기한이 지나면 영상과 후보를 다시 볼 수 없습니다.'),
  (title: '피해자 계정', text: '목록만 볼 수 있고 후보·결과 화면은 열리지 않습니다.'),
];

const List<_Tip> _victimTips = [
  (title: '사건 초대', text: '[채팅]에서 수락해야 그 사건이 목록에 보입니다.'),
  (title: '열람 기한', text: '기한이 지나면 영상과 시간을 다시 볼 수 없습니다.'),
  (title: '후보 확인', text: '후보 영상은 관리자 화면에서 관리자와 함께 봅니다.'),
];

const _accent = cornerColor; // 캔버스의 밝은 파랑 #3D8BFF

/// 2.13 이용 안내 (두 계정). 로그인 뒤 첫 화면이며 계정에 맞는 사용법만 보인다 (D-235).
/// 모양은 캔버스 "Info 전체 (레이아웃 + 서비스 정보)"를 따른다 (D-292):
/// 큰 영문 제목 히어로 · 기능 세 줄 · 소개 문장 · 사용 방법 카드 · 주요 기능 · 안내 · 맨 아래 큰 글자.
/// 3번(`meProvider`)만 부르고 새 API는 없다.
class InfoPage extends ConsumerWidget {
  const InfoPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final me = ref.watch(meProvider);
    ref.listen(meProvider, (_, next) {
      if (next.hasError) handleCommonError(context, next.error!);
    });
    return PageFrame(
      current: NavItem.info,
      maxWidth: 1152,
      child: me.when(
        loading: () => const Padding(
          padding: EdgeInsets.all(32),
          child: Center(child: CircularProgressIndicator()),
        ),
        error: (_, _) => const SizedBox.shrink(),
        data: (m) => _InfoBody(admin: m.isAdmin),
      ),
    );
  }
}

class _InfoBody extends StatelessWidget {
  const _InfoBody({required this.admin});

  final bool admin;

  @override
  Widget build(BuildContext context) {
    final narrow = isNarrow(context);
    final gap = narrow ? 48.0 : 72.0;
    final steps = admin ? _adminSteps : _victimSteps;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        // 배경의 빛 번짐은 PageFrame이 모든 화면에 깐다 (D-305)
        Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(height: narrow ? 24 : 40),
            _Hero(admin: admin),
            SizedBox(height: gap),
            const _FeatureRule(),
            SizedBox(height: gap),
            const _Lead(),
            SizedBox(height: gap),
            _Kicker(admin ? '관리자 계정 사용법' : '사건 관계자 계정 사용법'),
            const SizedBox(height: 18),
            Text(
              '${steps.length}단계로 끝나는 사건 처리',
              style: TextStyle(fontSize: narrow ? 30 : 40, fontWeight: FontWeight.w600, letterSpacing: -0.8),
            ),
            const SizedBox(height: 18),
            _Grid(
              minItemWidth: 200,
              children: [for (final (i, s) in steps.indexed) _StepCard(number: i + 1, step: s)],
            ),
            SizedBox(height: gap),
            _Grid(
              minItemWidth: 260,
              children: [for (final f in _features) _FeatureCard(tip: f)],
            ),
            SizedBox(height: gap),
            _Grid(
              minItemWidth: 240,
              children: [for (final t in admin ? _adminTips : _victimTips) _TipNote(tip: t)],
            ),
            SizedBox(height: gap),
            const _Signature(),
          ],
        ),
      ],
    );
  }
}

/// 둥근 빛 번짐. 가운데가 [alpha]만큼 진하고 바깥으로 갈수록 사라진다.
class _Glow extends StatelessWidget {
  const _Glow({required this.size, required this.color, required this.alpha});

  final double size;
  final Color color;
  final double alpha;

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [color.withValues(alpha: alpha), color.withValues(alpha: 0)],
            stops: const [0, 0.7],
          ),
        ),
      ),
    ),
  );
}

/// 작은 소제목 글자 (캔버스 `.fx-kicker`).
class _Kicker extends StatelessWidget {
  const _Kicker(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Text(
    text,
    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, letterSpacing: 1.04, color: subColor),
  );
}

/// 맨 위: 왼쪽 큰 영문 제목 "CANDIDATE / SCREENING"과 소개, 오른쪽 그라데이션 알약 "CCTV".
class _Hero extends StatelessWidget {
  const _Hero({required this.admin});

  final bool admin;

  @override
  Widget build(BuildContext context) {
    final narrow = isNarrow(context);
    Widget fit(Widget child) => FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: child);
    final text = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _Kicker(admin ? '주차장 관리자 안내' : '사건 관계자 안내'),
        const SizedBox(height: 18),
        fit(
          Text(
            'CANDIDATE',
            style: TextStyle(fontSize: narrow ? 52 : 92, fontWeight: FontWeight.w300, height: 1, letterSpacing: -2.7),
          ),
        ),
        const SizedBox(height: 18),
        fit(
          Text(
            'SCREENING',
            style: TextStyle(fontSize: narrow ? 58 : 104, fontWeight: FontWeight.w800, height: 1, letterSpacing: -3.1),
          ),
        ),
        const SizedBox(height: 30),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: const Text(
            '주차장 CCTV 영상의 개인정보를 가린 뒤 물피도주 후보 구간을 선별합니다. 최종 판단은 관리자가 합니다.',
            style: TextStyle(fontSize: 16, height: 1.8, color: subColor),
          ),
        ),
      ],
    );
    if (narrow) return text;
    return Row(
      children: [
        Expanded(child: text),
        const SizedBox(width: 40),
        const _HeroPill(),
      ],
    );
  }
}

class _HeroPill extends StatelessWidget {
  const _HeroPill();

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: Container(
      width: 440,
      height: 340,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(170),
        gradient: const LinearGradient(
          begin: Alignment(-1, -0.6),
          end: Alignment(1, 0.6),
          colors: [lineColor, progressColor, pointColor],
          stops: [0, 0.45, 1],
        ),
      ),
      child: const Stack(
        children: [
          Positioned(left: -40, top: -40, child: _Glow(size: 280, color: _accent, alpha: 0.7)),
          Positioned(
            right: 52,
            bottom: 44,
            child: Text(
              'CCTV',
              style: TextStyle(fontSize: 48, fontWeight: FontWeight.w800, letterSpacing: -1, color: Colors.white),
            ),
          ),
        ],
      ),
    ),
  );
}

/// 기능 세 개를 위쪽 검은 선 아래 한 줄로 (캔버스 `.fx-rule`).
class _FeatureRule extends StatelessWidget {
  const _FeatureRule();

  @override
  Widget build(BuildContext context) {
    const style = TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: pointColor);
    return Container(
      padding: const EdgeInsets.only(top: 12),
      decoration: const BoxDecoration(border: Border(top: BorderSide(color: inkColor))),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        spacing: 16,
        runSpacing: 8,
        children: [for (final f in _features) Text(f.title, style: style)],
      ),
    );
  }
}

/// 서비스 이름 두 줄과 오른쪽 짧은 안내.
class _Lead extends StatelessWidget {
  const _Lead();

  @override
  Widget build(BuildContext context) {
    final narrow = isNarrow(context);
    final title = Text(
      '주차장 CCTV 물피도주 후보 구간 선별 서비스\n사람이 보기 전에 먼저 걸러 드립니다.',
      style: TextStyle(fontSize: narrow ? 24 : 34, fontWeight: FontWeight.w600, height: 1.5, letterSpacing: -0.3),
    );
    const note = Text(
      '분석 결과는 후보 목록으로만 보이며, 관계자 열람은 관리·감독 안내에 동의한 뒤에만 열립니다.',
      style: TextStyle(fontSize: 15, height: 1.8, color: subColor),
    );
    if (narrow) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, spacing: 16, children: [title, note]);
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(child: title),
        const SizedBox(width: 40),
        const SizedBox(width: 320, child: note),
      ],
    );
  }
}

/// 폭에 맞춰 칸 수를 정하는 격자. 칸 하나가 [minItemWidth]보다 좁아지면 줄을 바꾼다.
/// 한 줄의 칸은 높이를 맞춘다(가장 큰 칸 기준).
class _Grid extends StatelessWidget {
  const _Grid({required this.minItemWidth, required this.children});

  final double minItemWidth;
  final List<Widget> children;

  static const _gap = 16.0;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final columns = math.max(
        1,
        math.min(children.length, ((constraints.maxWidth + _gap) / (minItemWidth + _gap)).floor()),
      );
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: _gap,
        children: [
          for (var start = 0; start < children.length; start += columns)
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                spacing: _gap,
                children: [
                  for (var i = start; i < start + columns; i++)
                    Expanded(child: i < children.length ? children[i] : const SizedBox.shrink()),
                ],
              ),
            ),
        ],
      );
    },
  );
}

/// 캔버스 `.fx-card`: 옅은 바탕, 1px 테두리, 모서리 20.
BoxDecoration get _fxCard => BoxDecoration(
  color: offWhiteColor,
  borderRadius: BorderRadius.circular(20),
  border: Border.all(color: lineColor),
);

class _StepCard extends StatelessWidget {
  const _StepCard({required this.number, required this.step});

  final int number;
  final _Step step;

  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 260),
    padding: const EdgeInsets.all(24),
    decoration: _fxCard,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          number.toString().padLeft(2, '0'),
          style: const TextStyle(fontSize: 52, fontWeight: FontWeight.w300, height: 1, color: _accent),
        ),
        const SizedBox(height: 14),
        Text(step.title, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
        const SizedBox(height: 14),
        Text(step.text, style: const TextStyle(fontSize: 15, height: 1.7, color: subColor)),
        const Spacer(),
        const SizedBox(height: 14),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.only(top: 12),
          decoration: const BoxDecoration(border: Border(top: BorderSide(color: lineColor))),
          child: Text(step.note, style: const TextStyle(fontSize: 13, color: pointColor)),
        ),
      ],
    ),
  );
}

class _FeatureCard extends StatelessWidget {
  const _FeatureCard({required this.tip});

  final _Tip tip;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(28),
    decoration: _fxCard,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 12,
      children: [
        Text(tip.title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600)),
        Text(tip.text, style: const TextStyle(fontSize: 14, height: 1.7, color: subColor)),
      ],
    ),
  );
}

/// 위쪽 검은 선 아래 굵은 제목 + 한 줄 설명 (캔버스 "안내").
class _TipNote extends StatelessWidget {
  const _TipNote({required this.tip});

  final _Tip tip;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.only(top: 14),
    decoration: const BoxDecoration(border: Border(top: BorderSide(color: inkColor))),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 2,
      children: [
        Text(tip.title, style: const TextStyle(fontSize: 13, height: 1.7, fontWeight: FontWeight.w600)),
        Text(tip.text, style: const TextStyle(fontSize: 13, height: 1.7, color: subColor)),
      ],
    ),
  );
}

/// 맨 아래 큰 글자 "ADMIN REVIEW". 화면보다 길면 오른쪽이 잘린다 (캔버스).
class _Signature extends StatelessWidget {
  const _Signature();

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: LayoutBuilder(
      builder: (context, constraints) {
        final size = math.min(176.0, constraints.maxWidth * 0.15);
        return ClipRect(
          child: Text.rich(
            TextSpan(
              children: [
                TextSpan(
                  text: 'ADMIN ',
                  style: TextStyle(fontSize: size, fontWeight: FontWeight.w800),
                ),
                TextSpan(
                  text: 'REVIEW',
                  style: TextStyle(fontSize: size, fontWeight: FontWeight.w300, color: _accent),
                ),
              ],
            ),
            maxLines: 1,
            softWrap: false,
            overflow: TextOverflow.clip,
            style: TextStyle(height: 0.9, letterSpacing: -size * 0.04, color: inkColor),
          ),
        );
      },
    ),
  );
}
