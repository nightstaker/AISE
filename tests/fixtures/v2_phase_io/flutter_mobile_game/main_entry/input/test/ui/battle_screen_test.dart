/// Tests for BattleScreen — turn-based combat display and outcomes.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:magic_tower/ui/battle_screen.dart';
import 'package:magic_tower/data/models.dart';

void main() {
  group('BattleScreen', () {
    /// Build the battle screen in a testable widget tree.
    Widget _buildWidget({
      required MonsterState monster,
      required int playerHp,
      required int playerAtk,
      required int playerDef,
      required bool playerWon,
      required int damageTaken,
      required bool isAnimating,
      required VoidCallback onBattleEnd,
      required VoidCallback onFlee,
    }) {
      return MaterialApp(
        home: Scaffold(
          body: BattleScreen(
            monster: monster,
            playerHp: playerHp,
            playerAtk: playerAtk,
            playerDef: playerDef,
            playerWon: playerWon,
            damageTaken: damageTaken,
            isAnimating: isAnimating,
            onBattleEnd: onBattleEnd,
            onFlee: onFlee,
          ),
        ),
      );
    }

    final testMonster = MonsterState(
      defId: 'goblin_001',
      name: 'Goblin',
      currentHp: 50,
      maxHp: 50,
      atk: 8,
      def: 2,
      expReward: 30,
      goldReward: 10,
      isBoss: false,
    );

    // ── Monster display ──────────────────────────────────────────────────

    testWidgets('displays monster name and sprite', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.text('Goblin'), findsOneWidget);
      expect(find.byType(Container), findsWidgets);
    });

    testWidgets('displays monster HP', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.textContaining('HP: 50'), findsOneWidget);
    });

    testWidgets('displays player stats', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.textContaining('HP: 100'), findsOneWidget);
      expect(find.textContaining('ATK: 10'), findsOneWidget);
      expect(find.textContaining('DEF: 5'), findsOneWidget);
    });

    // ── Victory / defeat messages ────────────────────────────────────────

    testWidgets('shows victory message when player won', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.textContaining('Victory'), findsOneWidget);
      expect(find.textContaining('Monster defeated'), findsOneWidget);
      expect(find.textContaining('Damage taken: 15'), findsOneWidget);
    });

    testWidgets('shows defeat message when player lost', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 10,
        playerAtk: 10,
        playerDef: 5,
        playerWon: false,
        damageTaken: 50,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.textContaining('Defeat'), findsOneWidget);
      expect(find.textContaining('defeated by Goblin'), findsOneWidget);
      expect(find.textContaining('Gold penalty'), findsOneWidget);
    });

    // ── Callbacks ────────────────────────────────────────────────────────

    testWidgets('onBattleEnd callback fires', (tester) async {
      var called = false;
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () => called = true,
        onFlee: () {},
      ));

      await tester.tap(find.text('继续').first);
      expect(called, isTrue);
    });

    testWidgets('onFlee callback fires', (tester) async {
      var called = false;
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () => called = true,
      ));

      await tester.tap(find.text('逃跑').first);
      expect(called, isTrue);
    });

    // ── Animation state ──────────────────────────────────────────────────

    testWidgets('hide buttons when animating', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: true,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.text('继续'), findsNothing);
      expect(find.text('逃跑'), findsNothing);
    });

    testWidgets('show buttons when animation complete', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.text('继续'), findsOneWidget);
      expect(find.text('逃跑'), findsOneWidget);
    });

    // ── Boss monster ─────────────────────────────────────────────────────

    testWidgets('displays boss indicator for boss monsters', (tester) async {
      final bossMonster = MonsterState(
        defId: 'dragon_001',
        name: 'Dragon',
        currentHp: 500,
        maxHp: 500,
        atk: 30,
        def: 10,
        expReward: 500,
        goldReward: 200,
        isBoss: true,
      );

      await tester.pumpWidget(_buildWidget(
        monster: bossMonster,
        playerHp: 200,
        playerAtk: 15,
        playerDef: 8,
        playerWon: false,
        damageTaken: 80,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.text('Dragon'), findsOneWidget);
      expect(find.textContaining('HP: 500'), findsOneWidget);
    });

    // ── Screen structure ─────────────────────────────────────────────────

    testWidgets('renders VS divider between player and monster', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.text('VS'), findsOneWidget);
    });

    testWidgets('renders battle log area', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(
        find.byType(Column),
        findsWidgets,
      );
    });

    // ── Edge cases ───────────────────────────────────────────────────────

    testWidgets('displays zero damage taken', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 100,
        playerDef: 50,
        playerWon: true,
        damageTaken: 0,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      expect(find.textContaining('Damage taken: 0'), findsOneWidget);
    });

    testWidgets('renders with black background', (tester) async {
      await tester.pumpWidget(_buildWidget(
        monster: testMonster,
        playerHp: 100,
        playerAtk: 10,
        playerDef: 5,
        playerWon: true,
        damageTaken: 15,
        isAnimating: false,
        onBattleEnd: () {},
        onFlee: () {},
      ));

      final scaffold = tester.widget<Scaffold>(find.byType(Scaffold).first);
      expect(scaffold.backgroundColor, equals(Colors.black87));
    });
  });
}
