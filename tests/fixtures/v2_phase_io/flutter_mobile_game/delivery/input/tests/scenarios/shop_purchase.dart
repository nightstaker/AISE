/// E2E scenario: shop_purchase
///
/// Trigger: {"action": "tap", "target": "red_potion_button"}
/// Effect: {"gold_decreased_by": 8, "red_potion_added": 1, "purchase_success": true}
///
/// Validates the shop purchase flow: player gold is deducted on successful
/// purchase, and the item is added to inventory. Gold insufficient = fail.

import 'package:magic_tower/data/models.dart';
import 'package:magic_tower/gameplay/shop_engine.dart';
import 'package:test/test.dart';

void main() {
  group('Shop Purchase — E2E Scenario', () {
    late ShopEngine shopEngine;

    setUp(() {
      shopEngine = ShopEngine();
      shopEngine.initialize(maxSlots: 10);

      // Populate shop with typical items
      shopEngine.addItem(
        id: 'red_potion',
        name: 'Red Potion',
        type: ItemType.redPotion,
        price: 8,
        healAmount: 20,
      );
      shopEngine.addItem(
        id: 'blue_potion',
        name: 'Blue Potion',
        type: ItemType.bluePotion,
        price: 15,
        healAmount: 50,
      );
      shopEngine.addItem(
        id: 'ruby',
        name: 'Ruby',
        type: ItemType.redGem,
        price: 20,
        atkBoost: 2,
      );
      shopEngine.addItem(
        id: 'sapphire',
        name: 'Sapphire',
        type: ItemType.blueGem,
        price: 20,
        defBoost: 2,
      );
    });

    test('gold decreased by 8 when red potion purchased with sufficient gold',
        () {
      final result = shopEngine.purchase(
        itemId: 'red_potion',
        playerGold: 50,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.success, isTrue);
      expect(result.goldRemaining, equals(42));
      expect(result.goldRemaining, equals(50 - 8));
      expect(result.itemAdded, isTrue);
      expect(result.healAmount, equals(20));
    });

    test('purchase fails when gold is insufficient', () {
      final result = shopEngine.purchase(
        itemId: 'red_potion',
        playerGold: 5,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.success, isFalse);
      expect(result.goldRemaining, equals(5));
      expect(result.itemAdded, isFalse);
      expect(result.message, contains('Not enough gold'));
    });

    test('purchase fails for non-existent item', () {
      final result = shopEngine.purchase(
        itemId: 'golden_key',
        playerGold: 100,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.success, isFalse);
      expect(result.goldRemaining, equals(100));
      expect(result.message, contains('not found'));
    });

    test('multiple purchases deduct gold cumulatively', () {
      // Buy two red potions
      var result = shopEngine.purchase(
        itemId: 'red_potion',
        playerGold: 50,
        playerAtk: 10,
        playerDef: 10,
      );
      expect(result.success, isTrue);
      expect(result.goldRemaining, equals(42));

      result = shopEngine.purchase(
        itemId: 'red_potion',
        playerGold: 42,
        playerAtk: 10,
        playerDef: 10,
      );
      expect(result.success, isTrue);
      expect(result.goldRemaining, equals(34));
    });

    test('purchase with insufficient gold leaves gold unchanged', () {
      final result = shopEngine.purchase(
        itemId: 'ruby',
        playerGold: 10,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.success, isFalse);
      expect(result.goldRemaining, equals(10),
          reason: 'Gold should not be deducted on failed purchase');
    });

    test('gem purchase boosts ATK correctly', () {
      final result = shopEngine.purchase(
        itemId: 'ruby',
        playerGold: 50,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.success, isTrue);
      expect(result.atkBoost, equals(2));
      expect(result.defBoost, equals(0));
      expect(result.goldRemaining, equals(30));
    });

    test('gem purchase boosts DEF correctly', () {
      final result = shopEngine.purchase(
        itemId: 'sapphire',
        playerGold: 50,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.success, isTrue);
      expect(result.defBoost, equals(2));
      expect(result.atkBoost, equals(0));
      expect(result.goldRemaining, equals(30));
    });

    test('purchaseMany deducts gold cumulatively', () {
      final results = shopEngine.purchaseMany(
        itemIds: ['red_potion', 'red_potion', 'ruby'],
        playerGold: 100,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(results.length, equals(3));
      expect(results[0].success, isTrue);
      expect(results[0].goldRemaining, equals(92));

      expect(results[1].success, isTrue);
      expect(results[1].goldRemaining, equals(84));

      expect(results[2].success, isTrue);
      expect(results[2].goldRemaining, equals(64));
    });

    test('purchaseMany fails when gold runs out mid-queue', () {
      final results = shopEngine.purchaseMany(
        itemIds: ['ruby', 'sapphire', 'red_potion'],
        playerGold: 35,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(results.length, equals(3));

      // Ruby costs 20, leaves 15
      expect(results[0].success, isTrue);
      expect(results[0].goldRemaining, equals(15));

      // Sapphire costs 20, insufficient
      expect(results[1].success, isFalse);
      expect(results[1].goldRemaining, equals(15));

      // Sapphire still costs 20, still insufficient
      expect(results[2].success, isFalse);
      expect(results[2].goldRemaining, equals(15));
    });

    test('purchase updates gold correctly for each item type', () {
      // Red potion: 8 gold
      expect(
        shopEngine.purchase(itemId: 'red_potion', playerGold: 50, playerAtk: 10, playerDef: 10).goldRemaining,
        equals(42),
      );

      // Blue potion: 15 gold
      expect(
        shopEngine.purchase(itemId: 'blue_potion', playerGold: 50, playerAtk: 10, playerDef: 10).goldRemaining,
        equals(35),
      );

      // Ruby: 20 gold
      expect(
        shopEngine.purchase(itemId: 'ruby', playerGold: 50, playerAtk: 10, playerDef: 10).goldRemaining,
        equals(30),
      );
    });

    test('purchase result message is human-readable', () {
      final result = shopEngine.purchase(
        itemId: 'red_potion',
        playerGold: 50,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.message, isNotEmpty);
      expect(result.message, contains('successful'));
    });
  });
}
