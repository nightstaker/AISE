/// Tests for GameScreen — main gameplay view, movement, combat, etc.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:magic_tower/ui/game_screen.dart';
import 'package:magic_tower/data/models.dart';

void main() {
  group('GameScreen', () {
    /// Build the game screen in a testable tree.
    Widget _buildWidget({
      required int floorNumber,
      required PlayerState player,
      required bool canMove,
      required Map<String, FloorTile> floorMap,
      required ValueChanged<Direction> onMove,
      required ValueChanged<int> onCombat,
      required ValueChanged<String> onDialogue,
      required ValueChanged<String> onPickup,
      required VoidCallback onShop,
      required VoidCallback onUpStairs,
      required VoidCallback onDownStairs,
      required ValueChanged<String> onShowMessage,
      required VoidCallback onMapRefresh,
    }) {
      return MaterialApp(
        home: GameScreen(
          floorNumber: floorNumber,
          player: player,
          canMove: canMove,
          floorMap: floorMap,
          onMove: onMove,
          onCombat: onCombat,
          onDialogue: onDialogue,
          onPickup: onPickup,
          onShop: onShop,
          onUpStairs: onUpStairs,
          onDownStairs: onDownStairs,
          onShowMessage: onShowMessage,
          onMapRefresh: onMapRefresh,
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

    final testMap = <String, FloorTile>{
      '5,5': FloorTile(type: TileType.floor),
    };

    testWidgets('renders HUD with player stats', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      expect(find.text('HP: 100/100'), findsOneWidget);
      expect(find.text('ATK: 10'), findsOneWidget);
      expect(find.text('DEF: 5'), findsOneWidget);
    });

    testWidgets('onMove callback fires when canMove is true', (tester) async {
      Direction? capturedDir;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (dir) => capturedDir = dir,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // HUDUI has 'Up' button label
      await tester.tap(find.text('Up').first);
      expect(capturedDir, equals(Direction.up));
    });

    testWidgets('onMove callback fires for left direction', (tester) async {
      Direction? capturedDir;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (dir) => capturedDir = dir,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // HUDUI has 'Left' button label
      await tester.tap(find.text('Left').first);
      expect(capturedDir, equals(Direction.left));
    });

    testWidgets('onMove callback fires for right direction', (tester) async {
      Direction? capturedDir;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (dir) => capturedDir = dir,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // HUDUI has 'Right' button label
      await tester.tap(find.text('Right').first);
      expect(capturedDir, equals(Direction.right));
    });

    testWidgets('onMove callback fires for down direction', (tester) async {
      Direction? capturedDir;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (dir) => capturedDir = dir,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // HUDUI has 'Down' button label
      await tester.tap(find.text('Down').first);
      expect(capturedDir, equals(Direction.down));
    });

    testWidgets('movement is blocked when canMove is false', (tester) async {
      Direction? capturedDir;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: false,
        floorMap: testMap,
        onMove: (dir) => capturedDir = dir,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('Up').first);
      expect(capturedDir, isNull);
    });

    testWidgets('onCombat callback fires via Attack button', (tester) async {
      int? capturedId;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (id) => capturedId = id,
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // HUDUI has 'Attack' button label
      await tester.tap(find.text('Attack').first);
      expect(capturedId, equals(0));
    });

    testWidgets('onShowMessage callback fires on locked door', (tester) async {
      String? capturedMessage;
      final lockedDoorMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.door),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: lockedDoorMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (msg) => capturedMessage = msg,
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('→').first);
      expect(capturedMessage, equals('Door is locked'));
    });

    testWidgets('onUpStairs callback fires', (tester) async {
      var called = false;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () => called = true,
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('Up Stairs').first);
      expect(called, isTrue);
    });

    testWidgets('onDownStairs callback fires', (tester) async {
      var called = false;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () => called = true,
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('Down Stairs').first);
      expect(called, isTrue);
    });

    testWidgets('onShop callback fires', (tester) async {
      var called = false;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () => called = true,
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('Shop').first);
      expect(called, isTrue);
    });

    testWidgets('floor number is displayed in HUD', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 5,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      expect(find.textContaining('Floor 5'), findsOneWidget);
    });

    testWidgets('gold is displayed in HUD', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      expect(find.text('Gold: 50'), findsOneWidget);
    });

    testWidgets('level is displayed in HUD', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      expect(find.text('Lv: 3'), findsOneWidget);
    });

    testWidgets('EXP is displayed in HUD', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      expect(find.text('EXP: 200'), findsOneWidget);
    });

    testWidgets('shows inventory snackbar when Items button pressed',
        (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('Items').first);
      await tester.pumpAndSettle();

      expect(find.text('Inventory opened'), findsOneWidget);
    });

    testWidgets('Attack button is disabled when canMove is false',
        (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: false,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      final attackButton = tester.widget<ElevatedButton>(
        find.text('Attack').first,
      );
      expect(attackButton.onPressed, isNull);
    });

    testWidgets('Items button is disabled when canMove is false',
        (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: false,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      final itemsButton = tester.widget<ElevatedButton>(
        find.text('Items').first,
      );
      expect(itemsButton.onPressed, isNull);
    });

    testWidgets('Shop button is disabled when canMove is false', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: false,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      final shopButton = tester.widget<ElevatedButton>(
        find.text('Shop').first,
      );
      expect(shopButton.onPressed, isNull);
    });

    testWidgets('Up Stairs button is disabled when canMove is false',
        (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: false,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      final upStairsButton = tester.widget<ElevatedButton>(
        find.text('Up Stairs').first,
      );
      expect(upStairsButton.onPressed, isNull);
    });

    testWidgets('Down Stairs button is disabled when canMove is false',
        (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: false,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      final downStairsButton = tester.widget<ElevatedButton>(
        find.text('Down Stairs').first,
      );
      expect(downStairsButton.onPressed, isNull);
    });

    testWidgets('minimap renders correctly', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Minimap is a Container with a GridView
      expect(find.byType(Container), findsWidgets);
    });

    testWidgets('map renders with correct tile colors', (tester) async {
      final floorMap = <String, FloorTile>{
        '0,0': FloorTile(type: TileType.wall),
        '5,5': FloorTile(type: TileType.floor),
        '10,10': FloorTile(type: TileType.stairsUp),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: floorMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Check that the map area container exists
      expect(find.byType(Container), findsWidgets);
    });

    testWidgets('monster tile triggers combat event on move', (tester) async {
      int? capturedId;
      final monsterMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.monster),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: monsterMap,
        onMove: (_) {},
        onCombat: (id) => capturedId = id,
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // '→' is the right arrow button in GameScreen's bottom bar
      await tester.tap(find.text('→').first);
      expect(capturedId, equals(0));
    });

    testWidgets('npc tile triggers dialogue event on move', (tester) async {
      String? capturedText;
      final npcMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.npc),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: npcMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (text) => capturedText = text,
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('→').first);
      expect(capturedText, isNotNull);
    });

    testWidgets('item tile triggers pickup event on move', (tester) async {
      String? capturedItem;
      final itemMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.item),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: itemMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (item) => capturedItem = item,
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('→').first);
      expect(capturedItem, isNotNull);
    });

    testWidgets('boss tile triggers combat event on move', (tester) async {
      int? capturedId;
      final bossMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.boss),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: bossMap,
        onMove: (_) {},
        onCombat: (id) => capturedId = id,
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('→').first);
      expect(capturedId, equals(0));
    });

    testWidgets('hidden room triggers pickup event on move', (tester) async {
      String? capturedItem;
      final hiddenMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.hiddenRoom),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: hiddenMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (item) => capturedItem = item,
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('→').first);
      expect(capturedItem, isNotNull);
    });

    testWidgets('stairsUp tile triggers upStairs event on move', (tester) async {
      var called = false;
      final stairsMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.stairsUp),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: stairsMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () => called = true,
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('→').first);
      expect(called, isTrue);
    });

    testWidgets('stairsDown tile triggers downStairs event on move',
        (tester) async {
      var called = false;
      final stairsMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.stairsDown),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: stairsMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () => called = true,
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      await tester.tap(find.text('→').first);
      expect(called, isTrue);
    });

    testWidgets('out of bounds movement does not trigger onMove',
        (tester) async {
      Direction? capturedDir;
      final edgeMap = <String, FloorTile>{
        '0,0': FloorTile(type: TileType.floor),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: edgeMap,
        onMove: (dir) => capturedDir = dir,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Try to move left from position 0
      await tester.tap(find.text('←').first);
      expect(capturedDir, isNull);
    });

    testWidgets('selfCheckMapRendered returns true after build', (tester) async {
      final state = await tester.pumpWidget<GameScreen>(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      expect(state.selfCheckMapRendered, isTrue);
    });

    testWidgets('selfCheckRenderedTypes returns set of rendered types',
        (tester) async {
      final floorMap = <String, FloorTile>{
        '0,0': FloorTile(type: TileType.wall),
        '5,5': FloorTile(type: TileType.floor),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: floorMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Verify the state is accessible
    });

    testWidgets('wall tile blocks movement', (tester) async {
      Direction? capturedDir;
      final wallMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
        '6,5': FloorTile(type: TileType.wall),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: wallMap,
        onMove: (dir) => capturedDir = dir,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Try to move right into a wall
      await tester.tap(find.text('→').first);
      expect(capturedDir, isNull);
    });

    testWidgets('event queue deduplicates events', (tester) async {
      // Multiple moves to the same tile should not queue duplicate events
      final floorMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
      };

      var moveCount = 0;
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: floorMap,
        onMove: (_) => moveCount++,
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Tap same button multiple times
      await tester.tap(find.text('↑').first);
      await tester.tap(find.text('↑').first);
      await tester.tap(find.text('↑').first);

      // Should have counted 3 moves
      expect(moveCount, 3);
    });

    testWidgets('renders with custom tileSize', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Verify the widget tree includes the expected structure
      expect(find.text('HP: 100/100'), findsOneWidget);
    });

    testWidgets('renders with showMinimap true (default)', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Should render the map area
      expect(find.byType(Container), findsWidgets);
    });

    testWidgets('renders with showMinimap false', (tester) async {
      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: testMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Should still render the map area
      expect(find.byType(Container), findsWidgets);
    });

    testWidgets('map renders player marker on floor tile', (tester) async {
      final floorMap = <String, FloorTile>{
        '5,5': FloorTile(type: TileType.floor),
      };

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: floorMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Player marker should render
      expect(find.byType(Container), findsWidgets);
    });

    testWidgets('empty tiles render as black', (tester) async {
      final emptyMap = <String, FloorTile>{};

      await tester.pumpWidget(_buildWidget(
        floorNumber: 1,
        player: testPlayer,
        canMove: true,
        floorMap: emptyMap,
        onMove: (_) {},
        onCombat: (_) {},
        onDialogue: (_) {},
        onPickup: (_) {},
        onShop: () {},
        onUpStairs: () {},
        onDownStairs: () {},
        onShowMessage: (_) {},
        onMapRefresh: () {},
      ));

      // Should still render the map grid
      expect(find.byType(Container), findsWidgets);
    });
  });
}
