/// E2E scenario: boss_fight_multi_phase
///
/// Trigger: {"action": "move", "target": "boss_tile"}
/// Effect: {"phase_change_at_hp": 250, "phase_2_atk": 40, "phase_2_def": 15, "phase_2_special": "rage"}
///
/// Validates that a BOSS fight has multiple phases. When the BOSS HP
/// drops to 250 (50% of initial 500), it enters phase 2 with ATK
/// increasing from 30 to 40 and DEF from 10 to 15.

import 'package:magic_tower/gameplay/boss_engine.dart';
import 'package:magic_tower/gameplay/battle_engine.dart';
import 'package:test/test.dart';

void main() {
  group('boss_fight_multi_phase — E2E Scenario', () {
    test('boss starts in phase 1 with initial stats', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(
            phaseId: 1,
            hpThreshold: 500,
            atk: 30,
            def: 10,
            special: 'normal',
          ),
          BossPhase(
            phaseId: 2,
            hpThreshold: 250,
            atk: 40,
            def: 15,
            special: 'rage',
          ),
        ],
      );

      expect(boss.bossHp, equals(500));
      expect(boss.bossAtk, equals(30));
      expect(boss.bossDef, equals(10));
      expect(boss.currentPhase, equals(1));
      expect(boss.phaseCount, equals(2));
      expect(boss.isDefeated, isFalse);
    });

    test('boss enters phase 2 when HP drops to 250', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(
            phaseId: 1,
            hpThreshold: 500,
            atk: 30,
            def: 10,
            special: 'normal',
          ),
          BossPhase(
            phaseId: 2,
            hpThreshold: 250,
            atk: 40,
            def: 15,
            special: 'rage',
          ),
        ],
      );

      // Deal 250 damage to reach threshold
      boss.takeDamage(250);

      expect(boss.bossHp, equals(250));
      expect(boss.currentPhase, equals(2));
      expect(boss.bossAtk, equals(40));
      expect(boss.bossDef, equals(15));
      expect(boss.isDefeated, isFalse);
    });

    test('boss stats update correctly at phase transition', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(
            phaseId: 1,
            hpThreshold: 500,
            atk: 30,
            def: 10,
            special: 'normal',
          ),
          BossPhase(
            phaseId: 2,
            hpThreshold: 250,
            atk: 40,
            def: 15,
            special: 'rage',
          ),
        ],
      );

      // Phase 1 stats
      expect(boss.bossAtk, equals(30));
      expect(boss.bossDef, equals(10));
      expect(boss.currentPhase, equals(1));

      // Deal enough damage to trigger phase 2
      boss.takeDamage(251);

      // Phase 2 stats should be updated
      expect(boss.bossAtk, equals(40));
      expect(boss.bossDef, equals(15));
      expect(boss.bossHp, equals(249));
      expect(boss.currentPhase, equals(2));
    });

    test('boss is defeated at HP 0', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(
            phaseId: 1,
            hpThreshold: 500,
            atk: 30,
            def: 10,
            special: 'normal',
          ),
        ],
      );

      boss.takeDamage(500);

      expect(boss.bossHp, equals(0));
      expect(boss.isDefeated, isTrue);
    });

    test('phase transition triggers at correct HP threshold', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(
            phaseId: 1,
            hpThreshold: 500,
            atk: 30,
            def: 10,
            special: 'normal',
          ),
          BossPhase(
            phaseId: 2,
            hpThreshold: 250,
            atk: 40,
            def: 15,
            special: 'rage',
          ),
        ],
      );

      // Deal 249 damage — still in phase 1 (HP = 251, above threshold)
      boss.takeDamage(249);
      expect(boss.currentPhase, equals(1));
      expect(boss.bossAtk, equals(30));

      // Deal 1 more damage — now enters phase 2 (HP = 250, at threshold)
      boss.takeDamage(1);
      expect(boss.currentPhase, equals(2));
      expect(boss.bossAtk, equals(40));
    });

    test('multi-phase boss with 3 phases', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 1000,
        atk: 25,
        def: 8,
        phases: [
          BossPhase(phaseId: 1, hpThreshold: 1000, atk: 25, def: 8, special: 'normal'),
          BossPhase(phaseId: 2, hpThreshold: 500, atk: 35, def: 12, special: 'fireBreath'),
          BossPhase(phaseId: 3, hpThreshold: 200, atk: 50, def: 18, special: 'rage'),
        ],
      );

      expect(boss.currentPhase, equals(1));
      expect(boss.bossAtk, equals(25));

      // Phase 1 → 2: HP drops to 500
      boss.takeDamage(500);
      expect(boss.currentPhase, equals(2));
      expect(boss.bossAtk, equals(35));

      // Phase 2 → 3: HP drops to 200
      boss.takeDamage(300);
      expect(boss.currentPhase, equals(3));
      expect(boss.bossAtk, equals(50));
    });

    test('boss turn logic with phase-aware AI', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(phaseId: 1, hpThreshold: 500, atk: 30, def: 10, special: 'normal'),
          BossPhase(phaseId: 2, hpThreshold: 250, atk: 40, def: 15, special: 'rage'),
        ],
      );

      // Set player stats for boss turn calculation
      boss.setPlayerHp(200);
      boss.setPlayerStats(atk: 15, def: 8);

      // In phase 1, boss should use normal attack stats
      final turn1 = boss.bossTurn();
      expect(turn1.action, isNotNull);
      expect(turn1.damage, greaterThanOrEqualTo(0));

      // Trigger phase 2
      boss.takeDamage(251);
      expect(boss.currentPhase, equals(2));

      // After phase transition, boss stats should be updated
      expect(boss.bossAtk, equals(40));
      expect(boss.bossDef, equals(15));
    });

    test('full battle simulation with phase transitions', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(phaseId: 1, hpThreshold: 500, atk: 30, def: 10, special: 'normal'),
          BossPhase(phaseId: 2, hpThreshold: 250, atk: 40, def: 15, special: 'rage'),
        ],
      );

      // Simulate full battle: player HP=300, ATK=20, DEF=10
      final result = boss.simulateBattle(
        playerHp: 300,
        playerAtk: 20,
        playerDef: 10,
        maxRounds: 50,
      );

      // Player should win eventually
      expect(result.playerWins, isTrue);
      expect(result.finalPhase, greaterThan(0));
      expect(result.turnLog.length, greaterThan(0));
      // Boss should have reached phase 2 during the fight
      expect(result.finalPhase, greaterThanOrEqualTo(2));
    });

    test('boss heal does not revive defeated boss', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(phaseId: 1, hpThreshold: 500, atk: 30, def: 10, special: 'normal'),
        ],
      );

      boss.takeDamage(500); // Defeat
      expect(boss.isDefeated, isTrue);
      expect(boss.bossHp, equals(0));

      // Heal should not revive
      boss.heal(100);
      expect(boss.isDefeated, isTrue);
      expect(boss.bossHp, equals(0));
    });

    test('takeDamage on defeated boss returns current HP', () {
      final boss = BossEngine();
      boss.initialize(
        hp: 500,
        atk: 30,
        def: 10,
        phases: [
          BossPhase(phaseId: 1, hpThreshold: 500, atk: 30, def: 10, special: 'normal'),
        ],
      );

      boss.takeDamage(500); // Defeat

      final result = boss.takeDamage(10); // Try to deal more damage
      expect(result, equals(0));
      expect(boss.isDefeated, isTrue);
    });
  });
}
