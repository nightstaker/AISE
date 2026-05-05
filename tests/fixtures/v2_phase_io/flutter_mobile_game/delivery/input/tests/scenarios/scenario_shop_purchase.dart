/// E2E Scenario 2: Shop Purchase Flow
///
/// Validates buying items from the shop, deducting gold, and
/// adding items to inventory.

import 'package:magic_tower/gameplay/player_mgr.dart';
import 'package:magic_tower/gameplay/inventory_mgr.dart';
import 'package:magic_tower/gameplay/shop_engine.dart';
import 'package:magic_tower/data/models.dart';
import 'package:test/test.dart';

void main() {
  group('E2E: Shop Purchase', () {
    late PlayerMgr player;
    late InventoryMgr inventory;
    late ShopEngine shop;

    setUp(() {
      player = PlayerMgr();
      player.initialize(
        hp: 100, maxHp: 100, atk: 10, def: 10, gold: 500, exp: 0, level: 1,
      );
      inventory = InventoryMgr();
      inventory.initialize();
      shop = ShopEngine();
      shop.initialize(maxSlots: 10);
    });

    test('player has enough gold to buy a red potion', () {
      expect(player.gold, equals(500));

      // Add a red potion to the shop
      shop.addItem(
        id: 'redPotion',
        name: 'Red Potion',
        type: ItemType.redPotion,
        price: 20,
        healAmount: 30,
      );

      // Buy the potion
      final result = shop.purchase(
        itemId: 'redPotion',
        playerGold: player.gold,
        playerAtk: player.atk,
        playerDef: player.def,
      );

      expect(result.success, isTrue);
      expect(result.goldRemaining, equals(480));
      expect(result.healAmount, equals(30));
    });

    test('player cannot buy item with insufficient gold', () {
      shop.addItem(
        id: 'bigSword',
        name: 'Big Sword',
        type: ItemType.sword,
        price: 600,
        atkBoost: 5,
      );

      final result = shop.purchase(
        itemId: 'bigSword',
        playerGold: player.gold,
        playerAtk: player.atk,
        playerDef: player.def,
      );

      expect(result.success, isFalse);
      expect(result.goldRemaining, equals(500));
    });

    test('buying adds item to inventory', () {
      shop.addItem(
        id: 'redGem',
        name: 'Red Gem',
        type: ItemType.redGem,
        price: 50,
        atkBoost: 2,
      );

      shop.purchase(
        itemId: 'redGem',
        playerGold: player.gold,
        playerAtk: player.atk,
        playerDef: player.def,
      );

      // Item should be in inventory
      expect(inventory.hasItem('redGem'), isTrue);
    });

    test('multiple purchases reduce gold correctly', () {
      shop.addItem(
        id: 'bluePotion',
        name: 'Blue Potion',
        type: ItemType.bluePotion,
        price: 15,
        healAmount: 20,
      );

      // Buy 3 potions
      for (int i = 0; i < 3; i++) {
        shop.purchase(
          itemId: 'bluePotion',
          playerGold: player.gold,
          playerAtk: player.atk,
          playerDef: player.def,
        );
      }

      expect(player.gold, equals(455)); // 500 - 3*15
    });

    test('player buys gem and gains atk', () {
      shop.addItem(
        id: 'blueGem',
        name: 'Blue Gem',
        type: ItemType.blueGem,
        price: 40,
        defBoost: 2,
      );

      final result = shop.purchase(
        itemId: 'blueGem',
        playerGold: player.gold,
        playerAtk: player.atk,
        playerDef: player.def,
      );

      expect(result.success, isTrue);
      expect(result.defBoost, equals(2));
      expect(result.atkBoost, equals(0));
    });
  });
}
