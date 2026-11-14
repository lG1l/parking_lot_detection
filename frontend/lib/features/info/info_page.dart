import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/theme.dart';
import '../../core/session.dart';
import '../../core/widgets/common.dart';

/// 사용법 한 단계: 카드 제목 · 아이콘 · 설명.
typedef _Step = ({String title, IconData icon, String text});

// 사용법 문구의 원본은 07장 2.13이다. 화면 흐름이 바뀌면 함께 고친다 (D-235).
const List<_Step> _adminSteps = [
  (title: '사건 연결', icon: Icons.person_add_alt, text: '[사건 관계자 연결]에서 피해자 계정 아이디를 입력해 사건에 초대합니다.'),
  (title: '영상 업로드', icon: Icons.upload_outlined, text: '위탁계약에 동의하고 CCTV 영상을 올립니다. 피해자가 초대를 수락하기 전에도 올릴 수 있습니다.'),
  (title: '진행도 확인', icon: Icons.autorenew, text: '[사건 목록]에서 영상을 눌러 진행도를 봅니다. 피해자가 차량과 파손 부위를 입력하면 분석이 시작됩니다.'),
  (title: '후보 확인', icon: Icons.search, text: '분석이 끝나면 관리·감독 안내에 동의한 뒤, 피해자와 함께 후보 영상을 확인하고 찾은 장면을 [찾음]으로 고정합니다.'),
  (title: '결과 확인', icon: Icons.check_circle_outline, text: '확인을 끝내면 결과 화면에서 고정한 장면의 원본 영상 기준 시간을 봅니다.'),
];

const List<_Step> _victimSteps = [
  (title: '초대 수락', icon: Icons.notifications_none, text: '[알림]에서 관리자의 사건 초대를 [수락]합니다.'),
  (title: '진행도 확인', icon: Icons.autorenew, text: '[사건 목록]에서 영상을 눌러 진행도를 봅니다.'),
  (title: '차량·파손 입력', icon: Icons.crop_free, text: '영상이 준비되면 내 차량과 파손 부위를 입력합니다.'),
  (title: '후보 확인', icon: Icons.search, text: '분석이 끝나면 관리자 화면에서 관리자와 함께 후보 영상을 확인합니다.'),
  (title: '시간 확인', icon: Icons.schedule, text: '확인이 끝나면 [사건 목록]에서 고정한 사건 지점의 시간을 다시 볼 수 있습니다. 경찰에 신고할 때 전달하세요.'),
];

/// 목록 상태 칩 안내: 이름 · 바탕색 · 글자색 · 설명 (캔버스 5.0 "목록의 상태 칩").
typedef _Chip = ({String label, Color background, Color foreground, String text});

const List<_Chip> _adminChips = [
  (label: '처리 중', background: progressChipColor, foreground: inkColor, text: '업로드·대기·분석이 끝나길 기다립니다'),
  (label: '사전 입력 필요', background: pointColor, foreground: offWhiteColor, text: '피해자가 차량과 파손 부위를 입력해야 합니다'),
  (label: '후보 선택 가능', background: pointColor, foreground: offWhiteColor, text: '후보를 확인할 수 있습니다'),
  (label: '확인 완료', background: doneChipColor, foreground: offWhiteColor, text: '모든 후보를 확인했습니다'),
  (label: '분석 실패', background: failChipColor, foreground: offWhiteColor, text: '영상 파일을 확인한 뒤 다시 올립니다'),
  (label: '수락 대기 중', background: progressChipColor, foreground: inkColor, text: '피해자가 연결을 아직 수락하지 않았습니다'),
];

const List<_Chip> _victimChips = [
  (label: '처리 중', background: progressChipColor, foreground: inkColor, text: '업로드·대기·분석이 끝나길 기다립니다'),
  (label: '사전 입력 필요', background: pointColor, foreground: offWhiteColor, text: '내 차량과 파손 부위를 입력해야 합니다'),
  (label: '분석 완료', background: doneChipColor, foreground: offWhiteColor, text: '관리자와 함께 후보를 확인합니다'),
  (label: '확인 완료', background: doneChipColor, foreground: offWhiteColor, text: '고정한 사건 지점의 시간을 볼 수 있습니다'),
  (label: '분석 실패', background: failChipColor, foreground: offWhiteColor, text: '관리자가 다시 시도하거나 영상을 다시 올립니다'),
];

typedef _Tip = ({String title, String text});

const List<_Tip> _adminTips = [
  (title: '관리·감독 안내', text: '후보 화면에 들어갈 때마다 동의 후 열람합니다.'),
  (title: '열람 기한', text: '기한이 지나면 영상과 후보를 다시 볼 수 없습니다.'),
  (title: '피해자 계정', text: '목록만 볼 수 있고 후보·결과 화면은 열리지 않습니다.'),
];

const List<_Tip> _victimTips = [
  (title: '사건 초대', text: '[알림]에서 수락해야 그 사건이 목록에 보입니다.'),
  (title: '열람 기한', text: '기한이 지나면 영상과 시간을 다시 볼 수 없습니다.'),
  (title: '후보 확인', text: '후보 영상은 관리자 화면에서 관리자와 함께 봅니다.'),
];

/// 2.13 이용 안내 (두 계정). 로그인 뒤 첫 화면이며 계정에 맞는 사용법만 보인다 (D-235).
/// 모양은 캔버스 "5.0 관리자 홈"(배너 · 서비스 소개 · 사용 방법 · 상태 칩)을 따른다 (D-237).
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
      child: me.when(
        loading: () => const Padding(
          padding: EdgeInsets.all(32),
          child: Center(child: CircularProgressIndicator()),
        ),
        error: (_, _) => const SizedBox.shrink(),
        data: (m) {
          final admin = m.isAdmin;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const _Hero(),
              const SizedBox(height: 32),
              const _Heading('서비스 소개'),
              const SizedBox(height: 6),
              const Text(
                '주차장 CCTV 영상에서 물피도주가 의심되는 차량과 구간을 찾아, 관리자가 확인할 후보로 정리하는 서비스입니다. '
                '영상 속 개인정보는 가린 상태로 분석합니다.',
                style: TextStyle(fontSize: 15, height: 1.7, color: noteColor),
              ),
              const SizedBox(height: 20),
              const _Grid(
                minItemWidth: 240,
                children: [
                  _FlatCard(title: '개인정보 마스킹', text: '개인정보가 가려진 장면만 분석에 사용합니다.'),
                  _FlatCard(title: '후보 구간 선별', text: '의심되는 차량과 구간을 점수순으로 골라냅니다.'),
                  _FlatCard(title: '관리자 최종 확인', text: '후보는 관리자가 직접 확인하고 결과를 저장합니다.'),
                ],
              ),
              const SizedBox(height: 40),
              _Heading(admin ? '관리자 계정 사용법' : '사건 관계자 계정 사용법'),
              const SizedBox(height: 6),
              const Text('영상 한 건을 처리하는 순서입니다. 최종 판단은 관리자가 합니다.', style: TextStyle(fontSize: 15, color: noteColor)),
              const SizedBox(height: 20),
              _Grid(
                minItemWidth: 200,
                children: [
                  for (final (i, s) in (admin ? _adminSteps : _victimSteps).indexed) _StepCard(number: i + 1, step: s),
                ],
              ),
              const SizedBox(height: 28),
              const Divider(height: 1),
              const SizedBox(height: 20),
              const Text('목록의 상태 칩', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
              const SizedBox(height: 14),
              _Grid(
                minItemWidth: 180,
                children: [for (final c in admin ? _adminChips : _victimChips) _ChipNote(chip: c)],
              ),
              const SizedBox(height: 24),
              _Grid(
                minItemWidth: 240,
                children: [
                  for (final t in admin ? _adminTips : _victimTips)
                    _FlatCard(title: t.title, text: t.text, small: true),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}

const _flatColor = Color(0xFFF6F7F9); // 캔버스 5.0의 옅은 회색 카드 바탕

class _Heading extends StatelessWidget {
  const _Heading(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Text(text, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600));
}

/// 맨 위 배너: 진한 남색 그라데이션 위 서비스 이름, 오른쪽에 기울인 두 아이콘 상자 (캔버스 5.0).
class _Hero extends StatelessWidget {
  const _Hero();

  @override
  Widget build(BuildContext context) {
    final narrow = isNarrow(context);
    return Container(
      constraints: BoxConstraints(minHeight: narrow ? 180 : 264),
      padding: EdgeInsets.symmetric(horizontal: narrow ? 24 : 64, vertical: 32),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(cardRadius),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [pointColor, subColor, Color(0xFF718096)],
          stops: [0, 0.6, 1],
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              spacing: 12,
              children: [
                Text(
                  '개인정보 마스킹 기반',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: offWhiteColor.withValues(alpha: 0.85),
                  ),
                ),
                Text(
                  '주차장 CCTV 물피도주 후보 구간 선별 서비스',
                  style: TextStyle(
                    fontSize: narrow ? 24 : 32,
                    fontWeight: FontWeight.w600,
                    height: 1.3,
                    color: offWhiteColor,
                  ),
                ),
              ],
            ),
          ),
          if (!narrow) const _HeroArt(),
        ],
      ),
    );
  }
}

class _HeroArt extends StatelessWidget {
  const _HeroArt();

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: SizedBox(
      width: 320,
      height: 220,
      child: Stack(
        children: [
          Positioned(
            left: 0,
            top: 40,
            child: Transform.rotate(
              angle: 10 * math.pi / 180,
              child: Container(
                width: 170,
                height: 170,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(44),
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [offWhiteColor.withValues(alpha: 0.95), progressColor.withValues(alpha: 0.55)],
                  ),
                ),
                child: const Icon(Icons.directions_car_outlined, size: 104, color: pointColor),
              ),
            ),
          ),
          Positioned(
            left: 120,
            top: 0,
            child: Transform.rotate(
              angle: -14 * math.pi / 180,
              child: Container(
                width: 200,
                height: 200,
                padding: const EdgeInsets.all(48),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(56),
                  gradient: const LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [progressColor, subColor, pointColor],
                    stops: [0, 0.42, 1],
                  ),
                  boxShadow: const [BoxShadow(color: Color(0x59141923), offset: Offset(0, 30), blurRadius: 60)],
                ),
                child: Opacity(
                  opacity: 0.78,
                  child: Image.asset('assets/images/logo.png', color: offWhiteColor, colorBlendMode: BlendMode.srcIn),
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

/// 폭에 맞춰 칸 수를 정하는 격자. 칸 하나가 [minItemWidth]보다 좁아지면 줄을 바꾼다.
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
      final width = (constraints.maxWidth - _gap * (columns - 1)) / columns;
      return Wrap(
        spacing: _gap,
        runSpacing: _gap,
        children: [for (final c in children) SizedBox(width: width, child: c)],
      );
    },
  );
}

class _FlatCard extends StatelessWidget {
  const _FlatCard({required this.title, required this.text, this.small = false});

  final String title;
  final String text;
  final bool small;

  @override
  Widget build(BuildContext context) => Container(
    padding: small ? const EdgeInsets.symmetric(horizontal: 18, vertical: 16) : const EdgeInsets.all(20),
    decoration: BoxDecoration(color: _flatColor, borderRadius: BorderRadius.circular(small ? 10 : 12)),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: small ? 6 : 8,
      children: [
        Text(
          title,
          style: TextStyle(fontSize: small ? 15 : 16, fontWeight: FontWeight.w600),
        ),
        Text(
          text,
          style: TextStyle(fontSize: small ? 13 : 14, height: 1.6, color: noteColor),
        ),
      ],
    ),
  );
}

class _StepCard extends StatelessWidget {
  const _StepCard({required this.number, required this.step});

  final int number;
  final _Step step;

  @override
  Widget build(BuildContext context) => Container(
    constraints: const BoxConstraints(minHeight: 180),
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: offWhiteColor,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: lineColor),
      boxShadow: cardShadow,
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 12,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Container(
              width: 32,
              height: 32,
              alignment: Alignment.center,
              decoration: const BoxDecoration(color: pointColor, shape: BoxShape.circle),
              child: Text(
                '$number',
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: offWhiteColor),
              ),
            ),
            Icon(step.icon, size: 28, color: pointColor),
          ],
        ),
        Text(step.title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
        Text(step.text, style: const TextStyle(fontSize: 14, height: 1.6, color: noteColor)),
      ],
    ),
  );
}

class _ChipNote extends StatelessWidget {
  const _ChipNote({required this.chip});

  final _Chip chip;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: 8,
    children: [
      // 칩은 글자 폭만큼만 (Row 안이라 alignment가 폭을 채우지 않는다)
      Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            height: 32,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            alignment: Alignment.center,
            decoration: BoxDecoration(color: chip.background, borderRadius: BorderRadius.circular(cardRadius)),
            child: Text(
              chip.label,
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: chip.foreground),
            ),
          ),
        ],
      ),
      Text(chip.text, style: const TextStyle(fontSize: 13, height: 1.5, color: noteColor)),
    ],
  );
}
