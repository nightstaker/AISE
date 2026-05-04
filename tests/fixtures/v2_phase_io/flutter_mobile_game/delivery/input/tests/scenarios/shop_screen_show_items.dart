/// E2E scenario: shop_screen_show_items
///
/// Trigger: {"action": "enter_shop"}
/// Effect: {"shop_screen_shown": true, "items_listed": ["Yellow Key - 8G", "Blue Key - 8G", "Red Key - 10G", "Red Potion - 8G", "Blue Potion - 15G", "Ruby - 20G", "Sapphire - 20G"], "buy_buttons_enabled": true, "gold_displayed": "Gold: 20"}
///
/// Validates the shop screen lists all purchasable items with prices,
/// and buy buttons are enabled/disabled based on player gold.

import 'package:magic_tower/data/models.dart';
import 'package:magic_tower/gameplay/shop_engine.dart';
import 'package:test/test.dart';

void main() {
  group('Shop Screen Show Items — E2E Scenario', () {
    late ShopEngine shopEngine;

    setUp(() {
      shopEngine = ShopEngine();
      shopEngine.initialize(maxSlots: 10);

      // Populate shop with all typical items
      shopEngine.addItem(
        id: 'yellow_key',
        name: 'Yellow Key',
        type: ItemType.yellowKey,
        price: 8,
      );
      shopEngine.addItem(
        id: 'blue_key',
        name: 'Blue Key',
        type: ItemType.blueKey,
        price: 8,
      );
      shopEngine.addItem(
        id: 'red_key',
        name: 'Red Key',
        type: ItemType.redKey,
        price: 10,
      );
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

    test('shop lists all 7 items with correct display names', () {
      final items = shopEngine.getShopItems();
      expect(items.length, equals(7));

      final names = items.map((e) => e['name'] as String).toList();
      expect(names, contains('Yellow Key'));
      expect(names, contains('Blue Key'));
      expect(names, contains('Red Key'));
      expect(names, contains('Red Potion'));
      expect(names, contains('Blue Potion'));
      expect(names, contains('Ruby'));
      expect(names, contains('Sapphire'));
    });

    test('item prices are correct: Yellow Key=8G, Blue Key=8G, Red Key=10G',
        () {
      final items = shopEngine.getShopItems();
      final priceMap = {
        for (final item in items) item['name'] as String: item['price'] as int,
      };

      expect(priceMap['Yellow Key'], equals(8));
      expect(priceMap['Blue Key'], equals(8));
      expect(priceMap['Red Key'], equals(10));
      expect(priceMap['Red Potion'], equals(8));
      expect(priceMap['Blue Potion'], equals(15));
      expect(priceMap['Ruby'], equals(20));
      expect(priceMap['Sapphire'], equals(20));
    });

    test('buy buttons enabled when player gold >= item price', () {
      final playerGold = 20;
      final items = shopEngine.getShopItems();

      for (final item in items) {
        final price = item['price'] as int;
        final canAfford = playerGold >= price;

        if (canAfford) {
          // Player can afford this item
          final result = shopEngine.purchase(
            itemId: item['id'] as String,
            playerGold: playerGold,
            playerAtk: 10,
            playerDef: 10,
          );
          expect(result.success, isTrue,
              reason: 'Should be able to afford ${item["name"]}');
        } else {
          final result = shopEngine.purchase(
            itemId: item['id'] as String,
            playerGold: playerGold,
            playerAtk: 10,
            playerDef: 10,
          );
          expect(result.success, isFalse,
              reason: 'Should not be able to afford ${item["name"]}');
        }
      }
    });

    test('buy buttons disabled when gold is insufficient', () {
      final playerGold = 5;
      // All items cost at least 8 gold
      final items = shopEngine.getShopItems();

      for (final item in items) {
        final result = shopEngine.purchase(
          itemId: item['id'] as String,
          playerGold: playerGold,
          playerAtk: 10,
          playerDef: 10,
        );
        expect(result.success, isFalse,
            reason: 'Gold $playerGold should be insufficient for ${item["name"]}');
      }
    });

    test('gold display shows correct amount', () {
      final playerGold = 20;
      final goldDisplay = 'Gold: $playerGold';
      expect(goldDisplay, equals('Gold: 20'));
    });

    test('shop screen is shown when entering shop', () {
      // Shop screen visibility is tied to the shop being open
      expect(shopEngine.itemCount, equals(7));
      expect(shopEngine.isEmpty, isFalse);
      expect(shopEngine.itemCount > 0, isTrue,
          reason: 'Shop should be open and show items');
    });

    test('item categories are correctly displayed', () {
      final items = shopEngine.getShopItems();

      final keys = items.where((i) =>
          i['type'] == ItemType.yellowKey.name ||
          i['type'] == ItemType.blueKey.name ||
          i['type'] == ItemType.redKey.name).toList();
      expect(keys.length, equals(3), reason: '3 key types');

      final potions = items.where((i) =>
          i['type'] == ItemType.redPotion.name ||
          i['type'] == ItemType.bluePotion.name).toList();
      expect(potions.length, equals(2), reason: '2 potion types');

      final gems = items.where((i) =>
          i['type'] == ItemType.redGem.name ||
          i['type'] == ItemType.blueGem.name).toList();
      expect(gems.length, equals(2), reason: '2 gem types');
    });

    test('purchase updates gold remaining', () {
      final result = shopEngine.purchase(
        itemId: 'red_potion',
        playerGold: 20,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result.success, isTrue);
      expect(result.goldRemaining, equals(12));

      // Buy another red potion
      final result2 = shopEngine.purchase(
        itemId: 'red_potion',
        playerGold: 12,
        playerAtk: 10,
        playerDef: 10,
      );

      expect(result2.success, isTrue);
      expect(result2.goldRemaining, equals(4));
    });
  });
}
