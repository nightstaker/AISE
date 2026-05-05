import 'package:magic_tower/data/models.dart';
import 'package:magic_tower/gameplay/shop_engine.dart';
import 'package:test/test.dart';

void main() {
  group('ShopEngine', () {
    late ShopEngine shop;

    setUp(() {
      shop = ShopEngine();
      shop.initialize(maxSlots: 5);
    });

    group('initialization', () {
      test('isInitialized returns true', () {
        expect(shop.isInitialized, isTrue);
      });

      test('maxSlots is correct', () {
        expect(shop.maxSlots, equals(5));
      });

      test('itemCount is 0', () {
        expect(shop.itemCount, equals(0));
      });

      test('isEmpty is true', () {
        expect(shop.isEmpty, isTrue);
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(() => fresh.itemCount, throwsStateError);
      });
    });

    group('addItem', () {
      test('adds redPotion for sale', () {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        expect(shop.itemCount, equals(1));
      });

      test('adds bluePotion for sale', () {
        shop.addItem(
          id: 'bluePotion',
          name: 'Blue Potion',
          type: ItemType.bluePotion,
          price: 100,
          healAmount: 150,
        );
        expect(shop.itemCount, equals(1));
      });

      test('adds redGem for sale', () {
        shop.addItem(
          id: 'redGem',
          name: 'Red Gem',
          type: ItemType.redGem,
          price: 50,
          atkBoost: 3,
        );
        expect(shop.itemCount, equals(1));
      });

      test('adds blueGem for sale', () {
        shop.addItem(
          id: 'blueGem',
          name: 'Blue Gem',
          type: ItemType.blueGem,
          price: 50,
          defBoost: 3,
        );
        expect(shop.itemCount, equals(1));
      });

      test('adds sword for sale', () {
        shop.addItem(
          id: 'sword',
          name: 'Sword',
          type: ItemType.redGem,
          price: 100,
          atkBoost: 5,
        );
        expect(shop.itemCount, equals(1));
      });

      test('adds armor for sale', () {
        shop.addItem(
          id: 'armor',
          name: 'Armor',
          type: ItemType.blueGem,
          price: 100,
          defBoost: 5,
        );
        expect(shop.itemCount, equals(1));
      });

      test('adds key for sale', () {
        shop.addItem(
          id: 'yellowKey',
          name: 'Yellow Key',
          type: ItemType.yellowKey,
          price: 20,
        );
        expect(shop.itemCount, equals(1));
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(
          () => fresh.addItem(
            id: 'test',
            name: 'Test',
            type: ItemType.redPotion,
            price: 10,
          ),
          throwsStateError,
        );
      });
    });

    group('removeItem', () {
      test('removes item by id', () {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        final result = shop.removeItem('redPotion');
        expect(result, isTrue);
        expect(shop.itemCount, equals(0));
      });

      test('returns false for non-existent item', () {
        final result = shop.removeItem('nonexistent');
        expect(result, isFalse);
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(() => fresh.removeItem('test'), throwsStateError);
      });
    });

    group('getItem', () {
      test('returns item details', () {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        final item = shop.getItem('redPotion');
        expect(item, isNotNull);
        expect(item!.name, equals('Red Potion'));
        expect(item.type, equals(ItemType.redPotion));
        expect(item.price, equals(30));
        expect(item.healAmount, equals(50));
      });

      test('returns null for non-existent item', () {
        expect(shop.getItem('nonexistent'), isNull);
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(() => fresh.getItem('test'), throwsStateError);
      });
    });

    group('hasItem', () {
      test('returns true for added item', () {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        expect(shop.hasItem('redPotion'), isTrue);
      });

      test('returns false for non-existent item', () {
        expect(shop.hasItem('nonexistent'), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(() => fresh.hasItem('test'), throwsStateError);
      });
    });

    group('getShopItems', () {
      test('returns all shop items', () {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        shop.addItem(
          id: 'bluePotion',
          name: 'Blue Potion',
          type: ItemType.bluePotion,
          price: 100,
          healAmount: 150,
        );
        final items = shop.getShopItems();
        expect(items.length, equals(2));
        expect(items[0]['id'], equals('redPotion'));
        expect(items[1]['id'], equals('bluePotion'));
      });

      test('returns empty list when no items', () {
        expect(shop.getShopItems(), isEmpty);
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(() => fresh.getShopItems(), throwsStateError);
      });
    });

    group('clearShop', () {
      test('removes all items', () {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        shop.addItem(
          id: 'bluePotion',
          name: 'Blue Potion',
          type: ItemType.bluePotion,
          price: 100,
          healAmount: 150,
        );
        shop.clearShop();
        expect(shop.itemCount, equals(0));
        expect(shop.isEmpty, isTrue);
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(() => fresh.clearShop(), throwsStateError);
      });
    });

    group('toJson / fromJson', () {
      test('serializes and deserializes correctly', () {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        shop.addItem(
          id: 'bluePotion',
          name: 'Blue Potion',
          type: ItemType.bluePotion,
          price: 100,
          healAmount: 150,
        );

        final json = shop.toJson();
        final restored = ShopEngine.fromJson(json);
        restored.initialize(maxSlots: 5);

        expect(restored.itemCount, equals(2));
        expect(restored.hasItem('redPotion'), isTrue);
        expect(restored.hasItem('bluePotion'), isTrue);
        expect(restored.getItem('redPotion')!.price, equals(30));
      });
    });

    // ── Purchase flow tests ────────────────────────────────────────────

    group('purchase', () {
      setUp(() {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        shop.addItem(
          id: 'bluePotion',
          name: 'Blue Potion',
          type: ItemType.bluePotion,
          price: 100,
          healAmount: 150,
        );
        shop.addItem(
          id: 'redGem',
          name: 'Red Gem',
          type: ItemType.redGem,
          price: 50,
          atkBoost: 3,
        );
      });

      test('purchases item with sufficient gold', () {
        final result = shop.purchase(
          itemId: 'redPotion',
          playerGold: 100,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(result.success, isTrue);
        expect(result.message, equals('Purchase successful'));
        expect(result.item, isNotNull);
        expect(result.item!.id, equals('redPotion'));
        expect(result.goldRemaining, equals(70));
        expect(result.itemAdded, isTrue);
        expect(result.healAmount, equals(50));
        expect(result.atkBoost, equals(0));
        expect(result.defBoost, equals(0));
      });

      test('fails with insufficient gold', () {
        final result = shop.purchase(
          itemId: 'redPotion',
          playerGold: 10,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(result.success, isFalse);
        expect(result.message, equals('Not enough gold'));
        expect(result.goldRemaining, equals(10));
        expect(result.item, isNull);
      });

      test('fails for non-existent item', () {
        final result = shop.purchase(
          itemId: 'nonexistent',
          playerGold: 100,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(result.success, isFalse);
        expect(result.message, equals('Item not found in shop'));
        expect(result.goldRemaining, equals(100));
      });

      test('returns correct boost values for gems', () {
        final result = shop.purchase(
          itemId: 'redGem',
          playerGold: 100,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(result.success, isTrue);
        expect(result.atkBoost, equals(3));
        expect(result.defBoost, equals(0));
        expect(result.healAmount, equals(0));
      });

      test('returns correct boost values for potions', () {
        final result = shop.purchase(
          itemId: 'bluePotion',
          playerGold: 200,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(result.success, isTrue);
        expect(result.healAmount, equals(150));
        expect(result.atkBoost, equals(0));
        expect(result.defBoost, equals(0));
      });

      test('deducts gold correctly', () {
        final result = shop.purchase(
          itemId: 'bluePotion',
          playerGold: 150,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(result.success, isTrue);
        expect(result.goldRemaining, equals(50));
      });

      test('fails when gold equals price', () {
        final result = shop.purchase(
          itemId: 'redPotion',
          playerGold: 30,
          playerAtk: 5,
          playerDef: 3,
        );
        // 30 >= 30 should succeed
        expect(result.success, isTrue);
        expect(result.goldRemaining, equals(0));
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(
          () => fresh.purchase(
            itemId: 'test',
            playerGold: 100,
            playerAtk: 5,
            playerDef: 3,
          ),
          throwsStateError,
        );
      });
    });

    group('purchaseMany', () {
      setUp(() {
        shop.addItem(
          id: 'redPotion',
          name: 'Red Potion',
          type: ItemType.redPotion,
          price: 30,
          healAmount: 50,
        );
        shop.addItem(
          id: 'bluePotion',
          name: 'Blue Potion',
          type: ItemType.bluePotion,
          price: 100,
          healAmount: 150,
        );
      });

      test('purchases multiple items sequentially', () {
        final results = shop.purchaseMany(
          itemIds: ['redPotion', 'bluePotion'],
          playerGold: 200,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(results.length, equals(2));
        expect(results[0].success, isTrue);
        expect(results[0].goldRemaining, equals(170));
        expect(results[1].success, isTrue);
        expect(results[1].goldRemaining, equals(70));
      });

      test('continues after first failure', () {
        final results = shop.purchaseMany(
          itemIds: ['bluePotion', 'redPotion'],
          playerGold: 50,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(results.length, equals(2));
        expect(results[0].success, isFalse);
        expect(results[0].goldRemaining, equals(50));
        // Second purchase succeeds because gold is still 50
        expect(results[1].success, isTrue);
        expect(results[1].goldRemaining, equals(20));
      });

      test('handles empty list', () {
        final results = shop.purchaseMany(
          itemIds: [],
          playerGold: 100,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(results, isEmpty);
      });

      test('throws when not initialized', () {
        final fresh = ShopEngine();
        expect(
          () => fresh.purchaseMany(
            itemIds: ['test'],
            playerGold: 100,
            playerAtk: 5,
            playerDef: 3,
          ),
          throwsStateError,
        );
      });
    });

    group('edge cases', () {
      test('shop full throws on addItem', () {
        shop.addItem(
          id: 'a',
          name: 'A',
          type: ItemType.redPotion,
          price: 10,
        );
        shop.addItem(
          id: 'b',
          name: 'B',
          type: ItemType.bluePotion,
          price: 10,
        );
        shop.addItem(
          id: 'c',
          name: 'C',
          type: ItemType.redGem,
          price: 10,
        );
        shop.addItem(
          id: 'd',
          name: 'D',
          type: ItemType.blueGem,
          price: 10,
        );
        shop.addItem(
          id: 'e',
          name: 'E',
          type: ItemType.yellowKey,
          price: 10,
        );
        expect(shop.itemCount, equals(5));
        expect(
          () => shop.addItem(
            id: 'f',
            name: 'F',
            type: ItemType.yellowKey,
            price: 10,
          ),
          throwsStateError,
        );
      });

      test('purchase with zero gold fails for priced item', () {
        final result = shop.purchase(
          itemId: 'redPotion',
          playerGold: 0,
          playerAtk: 5,
          playerDef: 3,
        );
        expect(result.success, isFalse);
        expect(result.message, equals('Not enough gold'));
      });
    });
  });
}
