import 'package:magic_tower/gameplay/inventory_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('InventoryMgr', () {
    late InventoryMgr inventory;

    setUp(() {
      inventory = InventoryMgr();
      inventory.initialize(maxSlots: 10);
    });

    group('initialization', () {
      test('isInitialized returns true', () {
        expect(inventory.isInitialized, isTrue);
      });

      test('maxSlots is correct', () {
        expect(inventory.maxSlots, equals(10));
      });

      test('isEmpty returns true initially', () {
        expect(inventory.isEmpty, isTrue);
      });

      test('count returns 0', () {
        expect(inventory.count, equals(0));
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.count, throwsStateError);
      });
    });

    group('addItem', () {
      test('adds redPotion', () {
        inventory.addItem('redPotion', 'Potion', ItemType.redPotion);
        expect(inventory.count, equals(1));
      });

      test('adds yellowKey', () {
        inventory.addItem('yellowKey', 'Yellow Key', ItemType.yellowKey);
        expect(inventory.count, equals(1));
      });

      test('adds blueKey', () {
        inventory.addItem('blueKey', 'Blue Key', ItemType.blueKey);
        expect(inventory.count, equals(1));
      });

      test('adds redKey', () {
        inventory.addItem('redKey', 'Red Key', ItemType.redKey);
        expect(inventory.count, equals(1));
      });

      test('adds bluePotion', () {
        inventory.addItem('bluePotion', 'Blue Potion', ItemType.bluePotion);
        expect(inventory.count, equals(1));
      });

      test('adds redGem', () {
        inventory.addItem('redGem', 'Red Gem', ItemType.redGem);
        expect(inventory.count, equals(1));
      });

      test('adds blueGem', () {
        inventory.addItem('blueGem', 'Blue Gem', ItemType.blueGem);
        expect(inventory.count, equals(1));
      });

      test('adds sword', () {
        inventory.addItem('sword', 'Sword', ItemType.sword);
        expect(inventory.count, equals(1));
      });

      test('adds armor', () {
        inventory.addItem('armor', 'Armor', ItemType.armor);
        expect(inventory.count, equals(1));
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.addItem('test', 'Test', ItemType.redPotion), throwsStateError);
      });
    });

    group('removeItem', () {
      test('removes item by id', () {
        inventory.addItem('redPotion', 'Potion', ItemType.redPotion);
        final result = inventory.removeItem('redPotion');
        expect(result, isTrue);
        expect(inventory.count, equals(0));
      });

      test('returns false for non-existent item', () {
        final result = inventory.removeItem('nonexistent');
        expect(result, isFalse);
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.removeItem('test'), throwsStateError);
      });
    });

    group('hasItem', () {
      test('returns true for added item', () {
        inventory.addItem('redPotion', 'Potion', ItemType.redPotion);
        expect(inventory.hasItem('redPotion'), isTrue);
      });

      test('returns false for non-existent item', () {
        expect(inventory.hasItem('nonexistent'), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.hasItem('test'), throwsStateError);
      });
    });

    group('getItemType', () {
      test('returns correct type for redPotion', () {
        inventory.addItem('redPotion', 'Potion', ItemType.redPotion);
        expect(inventory.getItemType('redPotion'), equals(ItemType.redPotion));
      });

      test('returns correct type for yellowKey', () {
        inventory.addItem('yellowKey', 'Yellow Key', ItemType.yellowKey);
        expect(inventory.getItemType('yellowKey'), equals(ItemType.yellowKey));
      });

      test('returns null for non-existent item', () {
        expect(inventory.getItemType('nonexistent'), isNull);
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.getItemType('test'), throwsStateError);
      });
    });

    group('useItem', () {
      test('uses redPotion and returns heal amount', () {
        inventory.addItem('redPotion', 'Potion', ItemType.redPotion, healAmount: 50);
        final result = inventory.useItem('redPotion');
        expect(result, equals(50));
        expect(inventory.hasItem('redPotion'), isFalse);
      });

      test('uses bluePotion and returns heal amount', () {
        inventory.addItem('bluePotion', 'Blue Potion', ItemType.bluePotion, healAmount: 100);
        final result = inventory.useItem('bluePotion');
        expect(result, equals(100));
        expect(inventory.hasItem('bluePotion'), isFalse);
      });

      test('uses redGem and returns atk boost', () {
        inventory.addItem('redGem', 'Red Gem', ItemType.redGem, atkBoost: 5);
        final result = inventory.useItem('redGem');
        expect(result, equals(5));
        expect(inventory.hasItem('redGem'), isFalse);
      });

      test('uses blueGem and returns def boost', () {
        inventory.addItem('blueGem', 'Blue Gem', ItemType.blueGem, defBoost: 5);
        final result = inventory.useItem('blueGem');
        expect(result, equals(5));
        expect(inventory.hasItem('blueGem'), isFalse);
      });

      test('uses sword and returns atk boost', () {
        inventory.addItem('sword', 'Sword', ItemType.sword, atkBoost: 10);
        final result = inventory.useItem('sword');
        expect(result, equals(10));
        expect(inventory.hasItem('sword'), isFalse);
      });

      test('uses armor and returns def boost', () {
        inventory.addItem('armor', 'Armor', ItemType.armor, defBoost: 10);
        final result = inventory.useItem('armor');
        expect(result, equals(10));
        expect(inventory.hasItem('armor'), isFalse);
      });

      test('returns 0 for keys (non-usable)', () {
        inventory.addItem('yellowKey', 'Yellow Key', ItemType.yellowKey);
        final result = inventory.useItem('yellowKey');
        expect(result, equals(0));
        expect(inventory.hasItem('yellowKey'), isTrue);
      });

      test('returns 0 for non-existent item', () {
        final result = inventory.useItem('nonexistent');
        expect(result, equals(0));
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.useItem('test'), throwsStateError);
      });
    });

    group('useKey', () {
      test('uses yellowKey', () {
        inventory.addItem('yellowKey', 'Yellow Key', ItemType.yellowKey);
        final result = inventory.useKey(KeyColor.yellow);
        expect(result, isTrue);
        expect(inventory.hasItem('yellowKey'), isFalse);
      });

      test('uses blueKey', () {
        inventory.addItem('blueKey', 'Blue Key', ItemType.blueKey);
        final result = inventory.useKey(KeyColor.blue);
        expect(result, isTrue);
        expect(inventory.hasItem('blueKey'), isFalse);
      });

      test('uses redKey', () {
        inventory.addItem('redKey', 'Red Key', ItemType.redKey);
        final result = inventory.useKey(KeyColor.red);
        expect(result, isTrue);
        expect(inventory.hasItem('redKey'), isFalse);
      });

      test('returns false for missing key', () {
        final result = inventory.useKey(KeyColor.red);
        expect(result, isFalse);
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.useKey(KeyColor.yellow), throwsStateError);
      });
    });

    group('hasKey', () {
      test('returns true for yellowKey', () {
        inventory.addItem('yellowKey', 'Yellow Key', ItemType.yellowKey);
        expect(inventory.hasKey(KeyColor.yellow), isTrue);
      });

      test('returns true for blueKey', () {
        inventory.addItem('blueKey', 'Blue Key', ItemType.blueKey);
        expect(inventory.hasKey(KeyColor.blue), isTrue);
      });

      test('returns true for redKey', () {
        inventory.addItem('redKey', 'Red Key', ItemType.redKey);
        expect(inventory.hasKey(KeyColor.red), isTrue);
      });

      test('returns false for missing key', () {
        expect(inventory.hasKey(KeyColor.yellow), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.hasKey(KeyColor.yellow), throwsStateError);
      });
    });

    group('clearInventory', () {
      test('removes all items', () {
        inventory.addItem('redPotion', 'Potion', ItemType.redPotion);
        inventory.addItem('yellowKey', 'Yellow Key', ItemType.yellowKey);
        inventory.addItem('redGem', 'Red Gem', ItemType.redGem);
        inventory.clearInventory();
        expect(inventory.count, equals(0));
        expect(inventory.isEmpty, isTrue);
      });

      test('throws when not initialized', () {
        final fresh = InventoryMgr();
        expect(() => fresh.clearInventory(), throwsStateError);
      });
    });

    group('toJson / fromJson', () {
      test('serializes and deserializes correctly', () {
        inventory.addItem('redPotion', 'Potion', ItemType.redPotion, healAmount: 50);
        inventory.addItem('yellowKey', 'Yellow Key', ItemType.yellowKey);
        inventory.addItem('redGem', 'Red Gem', ItemType.redGem, atkBoost: 5);

        final json = inventory.toJson();
        final restored = InventoryMgr.fromJson(json);
        restored.initialize(maxSlots: 10);

        expect(restored.count, equals(3));
        expect(restored.hasItem('redPotion'), isTrue);
        expect(restored.hasItem('yellowKey'), isTrue);
        expect(restored.hasItem('redGem'), isTrue);
      });
    });
  });
}
