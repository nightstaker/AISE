import 'package:magic_tower/gameplay/player_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('PlayerMgr', () {
    late PlayerMgr player;

    setUp(() {
      player = PlayerMgr();
      player.initialize(
        hp: 100,
        maxHp: 100,
        atk: 10,
        def: 5,
        gold: 50,
        exp: 0,
        level: 1,
      );
    });

    // ── Initialization ──────────────────────────────────────────

    group('initialization', () {
      test('sets all attributes correctly', () {
        expect(player.hp, equals(100));
        expect(player.maxHp, equals(100));
        expect(player.atk, equals(10));
        expect(player.def, equals(5));
        expect(player.gold, equals(50));
        expect(player.exp, equals(0));
        expect(player.level, equals(1));
      });

      test('isInitialized returns true after init', () {
        expect(player.isInitialized, isTrue);
      });

      test('throws StateError when accessing attributes before init',
          () {
        final fresh = PlayerMgr();
        expect(() => fresh.hp, throwsStateError);
        expect(() => fresh.atk, throwsStateError);
        expect(() => fresh.def, throwsStateError);
        expect(() => fresh.gold, throwsStateError);
        expect(() => fresh.exp, throwsStateError);
        expect(() => fresh.level, throwsStateError);
        expect(() => fresh.maxHp, throwsStateError);
      });

      test('throws StateError for methods before init', () {
        final fresh = PlayerMgr();
        expect(() => fresh.takeDamage(10), throwsStateError);
        expect(() => fresh.heal(10), throwsStateError);
        expect(() => fresh.modifyAtk(1), throwsStateError);
        expect(() => fresh.modifyDef(1), throwsStateError);
        expect(() => fresh.modifyGold(1), throwsStateError);
        expect(() => fresh.modifyExp(1), throwsStateError);
        expect(() => fresh.toJson(), throwsStateError);
      });

      test('default level is 1 when initialized', () {
        expect(player.level, equals(1));
      });
    });

    // ── Damage ──────────────────────────────────────────────────

    group('takeDamage', () {
      test('reduces HP by damage amount', () {
        player.takeDamage(20);
        expect(player.hp, equals(80));
      });

      test('does not go below 0', () {
        player.takeDamage(200);
        expect(player.hp, equals(0));
      });

      test('zero damage does not change HP', () {
        player.takeDamage(0);
        expect(player.hp, equals(100));
      });

      test('negative damage does not change HP', () {
        player.takeDamage(-10);
        expect(player.hp, equals(100));
      });

      test('dies when HP reaches 0', () {
        player.takeDamage(100);
        expect(player.isDead, isTrue);
      });

      test('is not dead when HP > 0', () {
        expect(player.isDead, isFalse);
      });

      test('multiple damage events accumulate', () {
        player.takeDamage(30);
        player.takeDamage(40);
        expect(player.hp, equals(30));
      });

      test('damage after death stays at 0', () {
        player.takeDamage(100);
        player.takeDamage(50);
        expect(player.hp, equals(0));
      });
    });

    // ── Heal ────────────────────────────────────────────────────

    group('heal', () {
      test('increases HP by heal amount', () {
        player.takeDamage(30);
        player.heal(20);
        expect(player.hp, equals(90));
      });

      test('does not exceed maxHp', () {
        player.heal(200);
        expect(player.hp, equals(100));
      });

      test('zero heal does nothing', () {
        player.heal(0);
        expect(player.hp, equals(100));
      });

      test('negative heal does nothing', () {
        player.heal(-10);
        expect(player.hp, equals(100));
      });

      test('heals dead player back to life', () {
        player.takeDamage(100);
        expect(player.isDead, isTrue);
        player.heal(50);
        expect(player.hp, equals(50));
        expect(player.isDead, isFalse);
      });

      test('heals back to full from partial', () {
        player.takeDamage(60);
        player.heal(60);
        expect(player.hp, equals(100));
      });

      test('heal above maxHp caps at maxHp', () {
        player.takeDamage(30);
        player.heal(100);
        expect(player.hp, equals(100));
      });
    });

    // ── Modify ATK ──────────────────────────────────────────────

    group('modifyAtk', () {
      test('increases ATK by delta', () {
        player.modifyAtk(5);
        expect(player.atk, equals(15));
      });

      test('decreases ATK by negative delta', () {
        player.modifyAtk(-3);
        expect(player.atk, equals(7));
      });

      test('ATK cannot go below 0', () {
        player.modifyAtk(-20);
        expect(player.atk, equals(0));
      });

      test('zero delta does nothing', () {
        player.modifyAtk(0);
        expect(player.atk, equals(10));
      });

      test('ATK clamps at 9999 upper bound', () {
        player.modifyAtk(9999);
        expect(player.atk, equals(9999));
      });
    });

    // ── Modify DEF ──────────────────────────────────────────────

    group('modifyDef', () {
      test('increases DEF by delta', () {
        player.modifyDef(3);
        expect(player.def, equals(8));
      });

      test('decreases DEF by negative delta', () {
        player.modifyDef(-2);
        expect(player.def, equals(3));
      });

      test('DEF cannot go below 0', () {
        player.modifyDef(-20);
        expect(player.def, equals(0));
      });

      test('zero delta does nothing', () {
        player.modifyDef(0);
        expect(player.def, equals(5));
      });

      test('DEF clamps at 9999 upper bound', () {
        player.modifyDef(9999);
        expect(player.def, equals(9999));
      });
    });

    // ── Modify Gold ─────────────────────────────────────────────

    group('modifyGold', () {
      test('increases gold', () {
        player.modifyGold(30);
        expect(player.gold, equals(80));
      });

      test('decreases gold', () {
        player.modifyGold(-20);
        expect(player.gold, equals(30));
      });

      test('gold cannot go below 0', () {
        player.modifyGold(-100);
        expect(player.gold, equals(0));
      });

      test('zero delta does nothing', () {
        player.modifyGold(0);
        expect(player.gold, equals(50));
      });

      test('gold clamps at 999999 upper bound', () {
        player.modifyGold(999999);
        expect(player.gold, equals(999999));
      });
    });

    // ── Modify EXP ──────────────────────────────────────────────

    group('modifyExp', () {
      test('increases exp', () {
        player.modifyExp(100);
        expect(player.exp, equals(100));
      });

      test('decreases exp', () {
        player.modifyExp(-30);
        expect(player.exp, equals(0));
      });

      test('exp cannot go below 0', () {
        player.modifyExp(-100);
        expect(player.exp, equals(0));
      });

      test('zero delta does nothing', () {
        player.modifyExp(0);
        expect(player.exp, equals(0));
      });

      test('exp clamps at 999999 upper bound', () {
        player.modifyExp(999999);
        expect(player.exp, equals(999999));
      });
    });

    // ── reset ───────────────────────────────────────────────────

    group('reset', () {
      test('resets all stats to defaults', () {
        player.takeDamage(50);
        player.modifyAtk(20);
        player.modifyDef(10);
        player.modifyGold(100);
        player.modifyExp(500);
        player.heal(30);

        player.reset();

        expect(player.hp, equals(0));
        expect(player.atk, equals(0));
        expect(player.def, equals(0));
        expect(player.gold, equals(0));
        expect(player.exp, equals(0));
        expect(player.level, equals(1));
      });

      test('reset does not affect isInitialized', () {
        player.reset();
        expect(player.isInitialized, isTrue);
      });

      test('isDead is false after reset (hp is 0 but not negative)',
          () {
        player.takeDamage(100);
        expect(player.isDead, isTrue);
        player.reset();
        expect(player.isDead, isTrue);
      });
    });

    // ── toJson ──────────────────────────────────────────────────

    group('toJson', () {
      test('returns correct map with current values', () {
        player.takeDamage(30);
        player.modifyAtk(5);
        player.modifyGold(20);

        final json = player.toJson();

        expect(json['hp'], equals(70));
        expect(json['atk'], equals(15));
        expect(json['def'], equals(5));
        expect(json['gold'], equals(70));
        expect(json['exp'], equals(0));
        expect(json['level'], equals(1));
      });

      test('toJson keys match expected format', () {
        final json = player.toJson();
        expect(json.keys, unorderedEquals(const [
          'hp',
          'atk',
          'def',
          'gold',
          'exp',
          'level',
        ]));
      });
    });

    // ── Edge cases ──────────────────────────────────────────────

    group('edge cases', () {
      test('maxHp is separate from current hp', () {
        player.takeDamage(50);
        expect(player.hp, equals(50));
        expect(player.maxHp, equals(100));
      });

      test('healing after damage respects maxHp cap', () {
        player.takeDamage(80);
        player.heal(50);
        expect(player.hp, equals(100));
        expect(player.maxHp, equals(100));
      });

      test('can modify stats after damage', () {
        player.takeDamage(50);
        player.modifyAtk(10);
        expect(player.atk, equals(20));
      });

      test('gold stays at 0 when spending more than owned', () {
        player.modifyGold(-100);
        expect(player.gold, equals(0));
      });

      test('level remains unchanged through other operations', () {
        player.takeDamage(50);
        player.heal(30);
        player.modifyGold(100);
        player.modifyExp(200);
        expect(player.level, equals(1));
      });
    });
  });
}
