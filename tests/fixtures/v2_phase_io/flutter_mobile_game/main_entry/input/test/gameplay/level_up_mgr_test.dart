import 'package:magic_tower/gameplay/level_up_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('LevelUpMgr', () {
    late LevelUpMgr levelUp;

    setUp(() {
      levelUp = LevelUpMgr();
      levelUp.initialize(
        initialLevel: 1,
        initialExp: 0,
        baseHp: 100,
        baseAtk: 10,
        baseDef: 5,
        hpPerLevel: 20,
        atkPerLevel: 3,
        defPerLevel: 2,
      );
    });

    group('initialization', () {
      test('isInitialized returns true', () {
        expect(levelUp.isInitialized, isTrue);
      });

      test('level is correct', () {
        expect(levelUp.level, equals(1));
      });

      test('exp is correct', () {
        expect(levelUp.exp, equals(0));
      });

      test('hp is correct', () {
        expect(levelUp.hp, equals(100));
      });

      test('atk is correct', () {
        expect(levelUp.atk, equals(10));
      });

      test('def is correct', () {
        expect(levelUp.def, equals(5));
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.level, throwsStateError);
      });
    });

    group('addExp', () {
      test('adds EXP', () {
        levelUp.addExp(50);
        expect(levelUp.exp, equals(50));
      });

      test('does not go below 0', () {
        levelUp.addExp(-50);
        expect(levelUp.exp, equals(0));
      });

      test('triggers level up when threshold reached', () {
        levelUp.addExp(100);
        expect(levelUp.level, equals(2));
        expect(levelUp.exp, equals(0));
      });

      test('multiple level ups', () {
        levelUp.addExp(300);
        expect(levelUp.level, equals(3));
        expect(levelUp.exp, equals(0));
      });

      test('does not level up below threshold', () {
        levelUp.addExp(99);
        expect(levelUp.level, equals(1));
        expect(levelUp.exp, equals(99));
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.addExp(50), throwsStateError);
      });
    });

    group('levelUp', () {
      test('increments level', () {
        levelUp.levelUp();
        expect(levelUp.level, equals(2));
      });

      test('increases HP', () {
        levelUp.levelUp();
        expect(levelUp.hp, equals(120));
      });

      test('increases ATK', () {
        levelUp.levelUp();
        expect(levelUp.atk, equals(13));
      });

      test('increases DEF', () {
        levelUp.levelUp();
        expect(levelUp.def, equals(7));
      });

      test('multiple level ups', () {
        levelUp.levelUp();
        levelUp.levelUp();
        expect(levelUp.level, equals(3));
        expect(levelUp.hp, equals(140));
        expect(levelUp.atk, equals(16));
        expect(levelUp.def, equals(9));
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.levelUp(), throwsStateError);
      });
    });

    group('consumeExp', () {
      test('subtracts EXP', () {
        levelUp.addExp(100);
        levelUp.consumeExp(50);
        expect(levelUp.exp, equals(50));
      });

      test('does not go below 0', () {
        levelUp.consumeExp(200);
        expect(levelUp.exp, equals(0));
      });

      test('does not change level', () {
        levelUp.addExp(100);
        levelUp.consumeExp(100);
        expect(levelUp.level, equals(1));
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.consumeExp(50), throwsStateError);
      });
    });

    group('checkLevelUp', () {
      test('levels up when exp >= threshold', () {
        levelUp.addExp(100);
        final leveled = levelUp.checkLevelUp();
        expect(leveled, isTrue);
        expect(levelUp.level, equals(2));
        expect(levelUp.exp, equals(0));
      });

      test('does not level up when below threshold', () {
        levelUp.addExp(50);
        final leveled = levelUp.checkLevelUp();
        expect(leveled, isFalse);
        expect(levelUp.level, equals(1));
      });

      test('multiple level ups', () {
        levelUp.addExp(300);
        final leveled = levelUp.checkLevelUp();
        expect(leveled, isTrue);
        expect(levelUp.level, equals(3));
        expect(levelUp.exp, equals(0));
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.checkLevelUp(), throwsStateError);
      });
    });

    group('canLevelUp', () {
      test('returns true when exp >= threshold', () {
        levelUp.addExp(100);
        expect(levelUp.canLevelUp(), isTrue);
      });

      test('returns false when below threshold', () {
        levelUp.addExp(50);
        expect(levelUp.canLevelUp(), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.canLevelUp(), throwsStateError);
      });
    });

    group('getExpThreshold', () {
      test('returns correct threshold for level 1', () {
        expect(levelUp.getExpThreshold(), equals(100));
      });

      test('returns correct threshold for level 2', () {
        levelUp.levelUp();
        expect(levelUp.getExpThreshold(), equals(100));
      });

      test('returns correct threshold for level 3', () {
        levelUp.levelUp();
        levelUp.levelUp();
        expect(levelUp.getExpThreshold(), equals(100));
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.getExpThreshold(), throwsStateError);
      });
    });

    group('toJson / fromJson', () {
      test('serializes and deserializes correctly', () {
        levelUp.addExp(50);
        levelUp.levelUp();
        levelUp.addExp(30);

        final json = levelUp.toJson();
        final restored = LevelUpMgr.fromJson(json);
        restored.initialize(
          initialLevel: 1,
          initialExp: 0,
          baseHp: 100,
          baseAtk: 10,
          baseDef: 5,
          hpPerLevel: 20,
          atkPerLevel: 3,
          defPerLevel: 2,
        );

        expect(restored.level, equals(2));
        expect(restored.exp, equals(30));
        expect(restored.hp, equals(120));
        expect(restored.atk, equals(13));
        expect(restored.def, equals(7));
      });
    });

    group('reset', () {
      test('resets to initial state', () {
        levelUp.addExp(100);
        levelUp.levelUp();
        levelUp.reset();
        expect(levelUp.level, equals(1));
        expect(levelUp.exp, equals(0));
        expect(levelUp.hp, equals(100));
        expect(levelUp.atk, equals(10));
        expect(levelUp.def, equals(5));
      });

      test('throws when not initialized', () {
        final fresh = LevelUpMgr();
        expect(() => fresh.reset(), throwsStateError);
      });
    });
  });
}
