import 'package:magic_tower/gameplay/battle_engine.dart';
import 'package:test/test.dart';

void main() {
  group('BattleEngine', () {
    late BattleEngine engine;

    setUp(() {
      engine = BattleEngine();
      engine.initialize();
    });

    group('calculateDamage', () {
      test('returns atk when atk > def', () {
        expect(BattleEngine.calculateDamage(10, 3), equals(7));
      });

      test('returns 1 when atk == def', () {
        expect(BattleEngine.calculateDamage(5, 5), equals(1));
      });

      test('returns 1 when atk < def', () {
        expect(BattleEngine.calculateDamage(3, 10), equals(1));
      });

      test('returns 1 when def is very high', () {
        expect(BattleEngine.calculateDamage(1, 100), equals(1));
      });

      test('returns 1 for zero damage', () {
        expect(BattleEngine.calculateDamage(0, 0), equals(1));
      });

      test('handles large values', () {
        expect(BattleEngine.calculateDamage(1000, 500), equals(500));
      });

      test('negative difference returns 1', () {
        expect(BattleEngine.calculateDamage(1, 50), equals(1));
      });
    });

    group('calculatePlayerDamage', () {
      test('correct damage when player atk > monster def', () {
        expect(BattleEngine.calculatePlayerDamage(10, 3), equals(7));
      });

      test('minimum 1 damage', () {
        expect(BattleEngine.calculatePlayerDamage(5, 5), equals(1));
        expect(BattleEngine.calculatePlayerDamage(3, 10), equals(1));
      });
    });

    group('calculateMonsterDamage', () {
      test('correct damage when monster atk > player def', () {
        expect(BattleEngine.calculateMonsterDamage(8, 2), equals(6));
      });

      test('minimum 1 damage', () {
        expect(BattleEngine.calculateMonsterDamage(5, 5), equals(1));
        expect(BattleEngine.calculateMonsterDamage(3, 10), equals(1));
      });
    });

    group('calculateRounds', () {
      test('player wins when player damage > 0 and can kill', () {
        final result = BattleEngine.calculateRounds(
          playerHp: 100,
          playerAtk: 10,
          playerDef: 5,
          monsterHp: 30,
          monsterAtk: 8,
          monsterDef: 3,
        );
        expect(result.playerWins, isTrue);
        expect(result.playerRoundsNeeded, 6);
        expect(result.monsterRoundsNeeded, 10);
        expect(result.playerHpRemaining, 70);
        expect(result.monsterHpRemaining, 0);
      });

      test('monster wins when monster kills player first', () {
        final result = BattleEngine.calculateRounds(
          playerHp: 20,
          playerAtk: 5,
          playerDef: 2,
          monsterHp: 50,
          monsterAtk: 10,
          monsterDef: 3,
        );
        expect(result.playerWins, isFalse);
        expect(result.playerRoundsNeeded, 10);
        expect(result.monsterRoundsNeeded, 3);
      });

      test('player wins with minimum damage', () {
        final result = BattleEngine.calculateRounds(
          playerHp: 100,
          playerAtk: 2,
          playerDef: 1,
          monsterHp: 10,
          monsterAtk: 1,
          monsterDef: 1,
        );
        expect(result.playerWins, isTrue);
        expect(result.playerRoundsNeeded, 5);
      });

      test('player cannot win when monster does 0 damage', () {
        // Monster does 0 damage (atk <= player def)
        final result = BattleEngine.calculateRounds(
          playerHp: 10,
          playerAtk: 5,
          playerDef: 10,
          monsterHp: 20,
          monsterAtk: 3,
          monsterDef: 0,
        );
        expect(result.playerWins, isTrue);
        expect(result.playerHpRemaining, 10);
        expect(result.monsterHpRemaining, 0);
      });

      test('handles exact kill rounds', () {
        final result = BattleEngine.calculateRounds(
          playerHp: 30,
          playerAtk: 10,
          playerDef: 5,
          monsterHp: 30,
          monsterAtk: 10,
          monsterDef: 5,
        );
        // Player deals 5 dmg per round, needs 6 rounds to kill monster (30/5=6)
        // Monster deals 5 dmg per round, 6 rounds = 30 dmg to player
        expect(result.playerRoundsNeeded, 6);
        expect(result.monsterRoundsNeeded, 6);
        expect(result.playerHpRemaining, 0);
        expect(result.monsterHpRemaining, 0);
      });

      test('throws when not initialized', () {
        final fresh = BattleEngine();
        expect(
          () => fresh.calculateRounds(
            playerHp: 100,
            playerAtk: 10,
            playerDef: 5,
            monsterHp: 30,
            monsterAtk: 8,
            monsterDef: 3,
          ),
          throwsStateError,
        );
      });
    });

    group('calculatePlayerRoundsNeeded', () {
      test('calculates rounds to kill monster', () {
        expect(BattleEngine.calculatePlayerRoundsNeeded(10, 3, 30), equals(6));
      });

      test('handles exact division', () {
        expect(BattleEngine.calculatePlayerRoundsNeeded(10, 0, 20), equals(2));
      });

      test('handles remainder', () {
        expect(BattleEngine.calculatePlayerRoundsNeeded(10, 0, 25), equals(3));
      });

      test('minimum 1 damage', () {
        expect(BattleEngine.calculatePlayerRoundsNeeded(5, 10, 100), equals(100));
      });

      test('returns 1 for 1 HP monster', () {
        expect(BattleEngine.calculatePlayerRoundsNeeded(10, 5, 1), equals(1));
      });
    });

    group('calculateMonsterRoundsNeeded', () {
      test('calculates rounds for monster to kill player', () {
        expect(BattleEngine.calculateMonsterRoundsNeeded(100, 10, 5), equals(10));
      });

      test('handles exact division', () {
        expect(BattleEngine.calculateMonsterRoundsNeeded(50, 10, 5), equals(5));
      });

      test('handles remainder', () {
        expect(BattleEngine.calculateMonsterRoundsNeeded(55, 10, 5), equals(6));
      });

      test('minimum 1 damage', () {
        expect(BattleEngine.calculateMonsterRoundsNeeded(100, 50, 10), equals(100));
      });

      test('returns 1 for 1 HP player', () {
        expect(BattleEngine.calculateMonsterRoundsNeeded(1, 10, 5), equals(1));
      });
    });

    group('initialize', () {
      test('sets initialized flag', () {
        expect(engine.isInitialized, isTrue);
      });

      test('already initialized does not throw', () {
        expect(() => engine.initialize(), returnsNormally);
      });
    });
  });
}
