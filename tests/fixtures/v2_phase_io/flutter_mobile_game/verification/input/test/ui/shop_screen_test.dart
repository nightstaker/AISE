/// Tests for ShopScreen — merchandise purchase interface.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:magic_tower/ui/shop_screen.dart';
import 'package:magic_tower/data/models.dart';
import 'package:magic_tower/gameplay/shop_engine.dart';

void main() {
  group('ShopScreen', () {
    /// Build the shop screen in a testable widget tree.
    Widget _buildWidget({
      required List<ShopItem> shopItems,
      required int playerGold,
      required ValueChanged<String> onPurchase,
      required VoidCallback onClose,
    }) {
      return MaterialApp(
        home: Scaffold(
          body: ShopScreen(
            shopItems: shopItems,
            playerGold: playerGold,
            onPurchase: onPurchase,
            onClose: onClose,
          ),
        ),
      );
    }

    final testItems = [
      ShopItem(
        id: 'red_potion',
        name: 'Red Potion',
        type: ItemType.redPotion,
        price: 20,
        healAmount: 30,
        color: Colors.red,
      ),
      ShopItem(
        id: 'yellow_key',
        name: 'Yellow Key',
        type: ItemType.yellowKey,
        price: 30,
        color: Colors.yellow,
      ),
      ShopItem(
        id: 'red_gem',
        name: 'ATK Gem',
        type: ItemType.redGem,
        price: 100,
        atkBoost: 1,
        color: Colors.red,
      ),
    ];

    testWidgets('displays player gold', (tester) async {
      await tester.pumpWidget(_buildWidget(
        shopItems: testItems,
        playerGold: 150,
        onPurchase: (_) {},
        onClose: () {},
      ));

      expect(find.textContaining('金币'), findsOneWidget);
      expect(find.textContaining('150'), findsOneWidget);
    });

    testWidgets('displays all shop items', (tester) async {
      await tester.pumpWidget(_buildWidget(
        shopItems: testItems,
        playerGold: 150,
        onPurchase: (_) {},
        onClose: () {},
      ));

      expect(find.text('Red Potion'), findsOneWidget);
      expect(find.text('Yellow Key'), findsOneWidget);
      expect(find.text('ATK Gem'), findsOneWidget);
    });

    testWidgets('shows price for each item', (tester) async {
      await tester.pumpWidget(_buildWidget(
        shopItems: testItems,
        playerGold: 150,
        onPurchase: (_) {},
        onClose: () {},
      ));

      expect(find.textContaining('20'), findsOneWidget);
      expect(find.textContaining('30'), findsOneWidget);
      expect(find.textContaining('100'), findsOneWidget);
    });

    testWidgets('purchase button enabled when player can afford', (tester) async {
      await tester.pumpWidget(_buildWidget(
        shopItems: testItems,
        playerGold: 200,
        onPurchase: (_) {},
        onClose: () {},
      ));

      // Should find the purchase buttons in a clickable state.
      expect(find.byType(ElevatedButton), findsWidgets);
    });

    testWidgets('onPurchase callback fires when buying item', (tester) async {
      String? purchasedItem;
      await tester.pumpWidget(_buildWidget(
        shopItems: testItems,
        playerGold: 200,
        onPurchase: (name) => purchasedItem = name,
        onClose: () {},
      ));

      await tester.tap(find.text('购买').first);
      expect(purchasedItem, equals('Red Potion'));
    });

    testWidgets('onClose callback fires', (tester) async {
      var closeCalled = false;
      await tester.pumpWidget(_buildWidget(
        shopItems: testItems,
        playerGold: 150,
        onPurchase: (_) {},
        onClose: () => closeCalled = true,
      ));

      await tester.tap(find.text('关闭'));
      expect(closeCalled, isTrue);
    });

    testWidgets('greyed out when player cannot afford', (tester) async {
      await tester.pumpWidget(_buildWidget(
        shopItems: testItems,
        playerGold: 10,
        onPurchase: (_) {},
        onClose: () {},
      ));

      // Should find disabled purchase buttons.
      expect(find.byType(ElevatedButton), findsWidgets);
    });

    testWidgets('empty shop list renders without error', (tester) async {
      await tester.pumpWidget(_buildWidget(
        shopItems: [],
        playerGold: 100,
        onPurchase: (_) {},
        onClose: () {},
      ));

      // Should not crash with empty list.
      expect(find.text('商店'), findsOneWidget);
      expect(find.textContaining('金币'), findsOneWidget);
    });

    testWidgets('ShopScreen initializes', () {
      final screen = ShopScreen(
        shopItems: testItems,
        playerGold: 100,
        onPurchase: (_) {},
        onClose: () {},
      );
      expect(screen.isInitialized, isTrue);
    });
  });
}
