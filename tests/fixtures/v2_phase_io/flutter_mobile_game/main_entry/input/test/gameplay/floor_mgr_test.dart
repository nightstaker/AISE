import 'package:magic_tower/gameplay/floor_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('FloorMgr', () {
    late FloorMgr floorMgr;

    setUp(() {
      floorMgr = FloorMgr();
      floorMgr.initialize(
        mapSize: 11,
        minFloor: 1,
        maxFloor: 10,
        startFloor: 1,
        startPosX: 5,
        startPosY: 10,
      );
    });

    group('initialization', () {
      test('isInitialized returns true', () {
        expect(floorMgr.isInitialized, isTrue);
      });

      test('currentFloor is startFloor', () {
        expect(floorMgr.currentFloor, equals(1));
      });

      test('playerPosition is correct', () {
        expect(floorMgr.playerX, equals(5));
        expect(floorMgr.playerY, equals(10));
      });

      test('mapSize is correct', () {
        expect(floorMgr.mapSize, equals(11));
      });

      test('throws when not initialized', () {
        final fresh = FloorMgr();
        expect(() => fresh.currentFloor, throwsStateError);
      });
    });

    group('movePlayer', () {
      test('moves player up', () {
        floorMgr.movePlayer(0, -1);
        expect(floorMgr.playerY, equals(9));
      });

      test('moves player down', () {
        floorMgr.movePlayer(0, 1);
        expect(floorMgr.playerY, equals(11));
      });

      test('moves player left', () {
        floorMgr.movePlayer(-1, 0);
        expect(floorMgr.playerX, equals(4));
      });

      test('moves player right', () {
        floorMgr.movePlayer(1, 0);
        expect(floorMgr.playerX, equals(6));
      });

      test('moves diagonally', () {
        floorMgr.movePlayer(1, 1);
        expect(floorMgr.playerX, equals(6));
        expect(floorMgr.playerY, equals(11));
      });

      test('moves player to stairsUp and returns true', () {
        floorMgr.setStairsUpAt(5, 0);
        final result = floorMgr.movePlayer(0, -10);
        expect(result, isTrue);
        expect(floorMgr.currentFloor, equals(2));
      });

      test('moves player to stairsDown and returns true', () {
        floorMgr.setStairsDownAt(5, 10);
        final result = floorMgr.movePlayer(0, 0);
        expect(result, isTrue);
        // Already at minFloor (1), so goDownFloor returns false and floor stays at 1
        expect(floorMgr.currentFloor, equals(1));
      });

      test('cannot move to walls', () {
        floorMgr.setWallAt(5, 9);
        final result = floorMgr.movePlayer(0, -1);
        expect(result, isFalse);
        expect(floorMgr.playerY, equals(10));
      });

      test('cannot move to monsters', () {
        floorMgr.setMonsterAt(5, 9, 'slime');
        final result = floorMgr.movePlayer(0, -1);
        expect(result, isFalse);
        expect(floorMgr.playerY, equals(10));
      });
    });

    group('stairs', () {
      test('hasStairsUp returns true when set', () {
        floorMgr.setStairsUpAt(5, 0);
        expect(floorMgr.hasStairsUp(5, 0), isTrue);
      });

      test('hasStairsUp returns false when not set', () {
        expect(floorMgr.hasStairsUp(5, 0), isFalse);
      });

      test('hasStairsDown returns true when set', () {
        floorMgr.setStairsDownAt(5, 10);
        expect(floorMgr.hasStairsDown(5, 10), isTrue);
      });

      test('hasStairsDown returns false when not set', () {
        expect(floorMgr.hasStairsDown(5, 10), isFalse);
      });

      test('getStairsUpPosition returns correct position', () {
        floorMgr.setStairsUpAt(3, 4);
        expect(floorMgr.getStairsUpPosition(), {'x': 3, 'y': 4});
      });

      test('getStairsDownPosition returns correct position', () {
        floorMgr.setStairsDownAt(7, 8);
        expect(floorMgr.getStairsDownPosition(), {'x': 7, 'y': 8});
      });
    });

    group('doors', () {
      test('setDoorColor sets door color', () {
        floorMgr.setDoorColor(5, 5, DoorColor.red);
        expect(floorMgr.getDoorColor(5, 5), DoorColor.red);
      });

      test('getDoorColor returns null for non-door', () {
        expect(floorMgr.getDoorColor(0, 0), isNull);
      });

      test('hasDoor returns true for door', () {
        floorMgr.setDoorColor(5, 5, DoorColor.blue);
        expect(floorMgr.hasDoor(5, 5), isTrue);
      });

      test('hasDoor returns false for non-door', () {
        expect(floorMgr.hasDoor(0, 0), isFalse);
      });

      test('unlockDoor removes door', () {
        floorMgr.setDoorColor(5, 5, DoorColor.red);
        floorMgr.unlockDoor(5, 5);
        expect(floorMgr.hasDoor(5, 5), isFalse);
      });
    });

    group('monsters', () {
      test('setMonsterAt sets monster', () {
        floorMgr.setMonsterAt(3, 3, 'slime');
        expect(floorMgr.getMonsterAt(3, 3), equals('slime'));
      });

      test('getMonsterAt returns null for empty tile', () {
        expect(floorMgr.getMonsterAt(0, 0), isNull);
      });

      test('removeMonster removes monster', () {
        floorMgr.setMonsterAt(3, 3, 'slime');
        floorMgr.removeMonster(3, 3);
        expect(floorMgr.getMonsterAt(3, 3), isNull);
      });

      test('hasMonster returns true', () {
        floorMgr.setMonsterAt(3, 3, 'slime');
        expect(floorMgr.hasMonster(3, 3), isTrue);
      });

      test('hasMonster returns false', () {
        expect(floorMgr.hasMonster(0, 0), isFalse);
      });
    });

    group('items', () {
      test('setItemAt sets item', () {
        floorMgr.setItemAt(3, 3, 'redPotion');
        expect(floorMgr.getItemAt(3, 3), equals('redPotion'));
      });

      test('getItemAt returns null for empty tile', () {
        expect(floorMgr.getItemAt(0, 0), isNull);
      });

      test('removeItem removes item', () {
        floorMgr.setItemAt(3, 3, 'redPotion');
        floorMgr.removeItem(3, 3);
        expect(floorMgr.getItemAt(3, 3), isNull);
      });

      test('hasItem returns true', () {
        floorMgr.setItemAt(3, 3, 'redPotion');
        expect(floorMgr.hasItem(3, 3), isTrue);
      });

      test('hasItem returns false', () {
        expect(floorMgr.hasItem(0, 0), isFalse);
      });
    });

    group('npcs', () {
      test('setNpcAt sets npc', () {
        floorMgr.setNpcAt(3, 3, 'wizard');
        expect(floorMgr.getNpcAt(3, 3), equals('wizard'));
      });

      test('getNpcAt returns null for empty tile', () {
        expect(floorMgr.getNpcAt(0, 0), isNull);
      });

      test('removeNpc removes npc', () {
        floorMgr.setNpcAt(3, 3, 'wizard');
        floorMgr.removeNpc(3, 3);
        expect(floorMgr.getNpcAt(3, 3), isNull);
      });

      test('hasNpc returns true', () {
        floorMgr.setNpcAt(3, 3, 'wizard');
        expect(floorMgr.hasNpc(3, 3), isTrue);
      });

      test('hasNpc returns false', () {
        expect(floorMgr.hasNpc(0, 0), isFalse);
      });
    });

    group('shop', () {
      test('setShopAt sets shop', () {
        floorMgr.setShopAt(3, 3);
        expect(floorMgr.hasShop(3, 3), isTrue);
      });

      test('hasShop returns false for empty tile', () {
        expect(floorMgr.hasShop(0, 0), isFalse);
      });

      test('removeShop removes shop', () {
        floorMgr.setShopAt(3, 3);
        floorMgr.removeShop(3, 3);
        expect(floorMgr.hasShop(3, 3), isFalse);
      });
    });

    group('boss', () {
      test('setBossAt sets boss', () {
        floorMgr.setBossAt(3, 3, 'dragon');
        expect(floorMgr.getBossAt(3, 3), equals('dragon'));
      });

      test('getBossAt returns null for empty tile', () {
        expect(floorMgr.getBossAt(0, 0), isNull);
      });

      test('removeBoss removes boss', () {
        floorMgr.setBossAt(3, 3, 'dragon');
        floorMgr.removeBoss(3, 3);
        expect(floorMgr.getBossAt(3, 3), isNull);
      });

      test('hasBoss returns true', () {
        floorMgr.setBossAt(3, 3, 'dragon');
        expect(floorMgr.hasBoss(3, 3), isTrue);
      });

      test('hasBoss returns false', () {
        expect(floorMgr.hasBoss(0, 0), isFalse);
      });
    });

    group('floor transitions', () {
      test('goes up floor', () {
        floorMgr.goUpFloor();
        expect(floorMgr.currentFloor, equals(2));
      });

      test('goes down floor', () {
        floorMgr.goDownFloor();
        expect(floorMgr.currentFloor, equals(0));
      });

      test('cannot go below minFloor', () {
        floorMgr.currentFloor = 1;
        floorMgr.goDownFloor();
        expect(floorMgr.currentFloor, equals(1));
      });

      test('cannot go above maxFloor', () {
        floorMgr.currentFloor = 10;
        floorMgr.goUpFloor();
        expect(floorMgr.currentFloor, equals(10));
      });

      test('setFloor sets current floor', () {
        floorMgr.setFloor(5);
        expect(floorMgr.currentFloor, equals(5));
      });
    });

    group('clearFloor', () {
      test('clears all entities', () {
        floorMgr.setMonsterAt(3, 3, 'slime');
        floorMgr.setItemAt(4, 4, 'redPotion');
        floorMgr.setNpcAt(5, 5, 'wizard');
        floorMgr.setShopAt(6, 6);
        floorMgr.setBossAt(7, 7, 'dragon');
        floorMgr.setDoorColor(8, 8, DoorColor.red);

        floorMgr.clearFloor();

        expect(floorMgr.getMonsterAt(3, 3), isNull);
        expect(floorMgr.getItemAt(4, 4), isNull);
        expect(floorMgr.getNpcAt(5, 5), isNull);
        expect(floorMgr.hasShop(6, 6), isFalse);
        expect(floorMgr.getBossAt(7, 7), isNull);
        expect(floorMgr.hasDoor(8, 8), isFalse);
      });
    });

    group('toJson / fromJson', () {
      test('serializes and deserializes correctly', () {
        floorMgr.setMonsterAt(3, 3, 'slime');
        floorMgr.setItemAt(4, 4, 'redPotion');
        floorMgr.setNpcAt(5, 5, 'wizard');
        floorMgr.setBossAt(6, 6, 'dragon');
        floorMgr.setStairsUpAt(7, 7);
        floorMgr.setStairsDownAt(8, 8);
        floorMgr.setDoorColor(9, 9, DoorColor.red);
        floorMgr.currentFloor = 5;

        final json = floorMgr.toJson();
        final restored = FloorMgr.fromJson(json);
        restored.initialize(
          mapSize: 11,
          minFloor: 1,
          maxFloor: 10,
          startFloor: 1,
          startPosX: 5,
          startPosY: 10,
        );

        expect(restored.currentFloor, equals(5));
        expect(restored.getMonsterAt(3, 3), equals('slime'));
        expect(restored.getItemAt(4, 4), equals('redPotion'));
        expect(restored.getNpcAt(5, 5), equals('wizard'));
        expect(restored.getBossAt(6, 6), equals('dragon'));
        expect(restored.hasStairsUp(7, 7), isTrue);
        expect(restored.hasStairsDown(8, 8), isTrue);
        expect(restored.getDoorColor(9, 9), DoorColor.red);
      });
    });
  });
}
