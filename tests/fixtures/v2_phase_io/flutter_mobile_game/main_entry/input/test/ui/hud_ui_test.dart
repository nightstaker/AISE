/// Tests for HUDUI — player stats display and action buttons.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:magic_tower/ui/hud_ui.dart';
import 'package:magic_tower/data/models.dart';

void main() {
  group('HUDUI', () {
    /// Build the HUD widget in a testable tree.
    Widget _buildWidget({
      required PlayerState player,
      required int floorNumber,
      bool showActionButtons = true,
      required VoidCallback onUp,
      required VoidCallback onDown,
      required VoidCallback onLeft,
      required VoidCallback onRight,
      required VoidCallback onAttack,
      required VoidCallback onInventory,
    }) {
      return MaterialApp(
        home: Scaffold(
          body: HUDUI(
            player: player,
            floorNumber: floorNumber,
            showActionButtons: showActionButtons,
            onUp: onUp,
            onDown: onDown,
            onLeft: onLeft,
            onRight: onRight,
            onAttack: onAttack,
            onInventory: onInventory,
          ),
        ),
      );
    }

    final testPlayer = PlayerState(
      hp: 100,
      maxHp: 100,
      atk: 10,
      def: 5,
      gold: 50,
      exp: 200,
      level: 3,
    );

    testWidgets('displays player stats correctly', (tester) async {
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      ));

      expect(find.text('HP: 100/100'), findsOneWidget);
      expect(find.text('ATK: 10'), findsOneWidget);
      expect(find.text('DEF: 5'), findsOneWidget);
      expect(find.text('Gold: 50'), findsOneWidget);
      expect(find.text('Lv: 3'), findsOneWidget);
    });

    testWidgets('displays floor number', (tester) async {
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 5,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      ));

      expect(find.text('Floor 5'), findsOneWidget);
    });

    testWidgets('action buttons are visible when showActionButtons is true',
        (tester) async {
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        showActionButtons: true,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      ));

      // The HUD should have action buttons at the bottom.
      expect(find.byType(ElevatedButton), findsNWidgets(6));
    });

    testWidgets('action buttons are hidden when showActionButtons is false',
        (tester) async {
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        showActionButtons: false,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      ));

      // Should not have the action buttons.
      expect(find.text('Up'), findsNothing);
    });

    testWidgets('onUp callback fires', (tester) async {
      var upCalled = false;
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        onUp: () => upCalled = true,
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      ));

      await tester.tap(find.text('Up').first);
      expect(upCalled, isTrue);
    });

    testWidgets('onDown callback fires', (tester) async {
      var downCalled = false;
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        onUp: () {},
        onDown: () => downCalled = true,
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      ));

      await tester.tap(find.text('Down').first);
      expect(downCalled, isTrue);
    });

    testWidgets('onLeft callback fires', (tester) async {
      var leftCalled = false;
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        onUp: () {},
        onDown: () {},
        onLeft: () => leftCalled = true,
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      ));

      await tester.tap(find.text('Left').first);
      expect(leftCalled, isTrue);
    });

    testWidgets('onRight callback fires', (tester) async {
      var rightCalled = false;
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () => rightCalled = true,
        onAttack: () {},
        onInventory: () {},
      ));

      await tester.tap(find.text('Right').first);
      expect(rightCalled, isTrue);
    });

    testWidgets('onAttack callback fires', (tester) async {
      var attackCalled = false;
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () => attackCalled = true,
        onInventory: () {},
      ));

      await tester.tap(find.text('Attack').first);
      expect(attackCalled, isTrue);
    });

    testWidgets('onInventory callback fires', (tester) async {
      var inventoryCalled = false;
      await tester.pumpWidget(_buildWidget(
        player: testPlayer,
        floorNumber: 1,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () => inventoryCalled = true,
      ));

      await tester.tap(find.text('Items').first);
      expect(inventoryCalled, isTrue);
    });

    test('initialize and isInitialized work', () {
      final hud = HUDUI(
        player: testPlayer,
        floorNumber: 1,
        onUp: () {},
        onDown: () {},
        onLeft: () {},
        onRight: () {},
        onAttack: () {},
        onInventory: () {},
      );
      hud.initialize();
      expect(hud.isInitialized, isTrue);
    });
  });
}
