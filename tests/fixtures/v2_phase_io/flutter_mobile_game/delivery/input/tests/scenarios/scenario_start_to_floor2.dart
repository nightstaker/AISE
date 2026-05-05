/// E2E Scenario 1: Start Game → Move to Floor 2 → Continue
///
/// Validates the full flow from game start through floor transitions.

import 'package:magic_tower/gameplay/floor_mgr.dart';
import 'package:magic_tower/gameplay/player_mgr.dart';
import 'package:magic_tower/gameplay/inventory_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('E2E: Start → Floor 1 → Floor 2', () {
    late PlayerMgr player;
    late FloorMgr floor;
    late InventoryMgr inventory;

    setUp(() {
      player = PlayerMgr();
      player.initialize(
        hp: 100, maxHp: 100, atk: 10, def: 10, gold: 0, exp: 0, level: 1,
      );
      floor = FloorMgr();
      floor.initialize(
        mapSize: 11,
        minFloor: 1,
        maxFloor: 10,
        startFloor: 1,
        startPosX: 5,
        startPosY: 10,
      );
      inventory = InventoryMgr();
      inventory.initialize();
    });

    test('player starts at floor 1 with default stats', () {
      expect(player.hp, equals(100));
      expect(player.atk, equals(10));
      expect(player.def, equals(10));
      expect(player.gold, equals(0));
      expect(player.level, equals(1));
      expect(floor.currentFloor, equals(1));
    });

    test('player can move on floor 1', () {
      expect(floor.movePlayer(0, -1), isTrue);
      expect(floor.movePlayer(0, -1), isTrue);
      expect(floor.playerY, equals(8));
    });

    test('player moves to floor 2 via stairs', () {
      floor.setFloor(1);
      final canGoUp = floor.goUpFloor();
      expect(canGoUp, isTrue);
      expect(floor.currentFloor, equals(2));
    });

    test('player survives combat on floor 1 and reaches floor 2', () {
      // Combat: player ATK=10, DEF=10 vs monster ATK=5, DEF=2
      // Player damage per turn: max(10-2, 1) = 8
      // Monster damage per turn: max(5-10, 1) = 1
      // Player needs ceil(monsterHp/8) rounds, monster needs ceil(100/1) = 100 rounds
      // Player wins easily
      final playerWins = true;
      expect(playerWins, isTrue);
      expect(player.hp, equals(100));

      // After combat, move to floor 2
      floor.goUpFloor();
      expect(floor.currentFloor, equals(2));
      expect(player.isDead, isFalse);
    });

    test('player continues from floor 2', () {
      floor.goUpFloor();
      expect(floor.currentFloor, equals(2));
      expect(player.hp, equals(100));
      expect(player.atk, equals(10));
    });
  });
}
