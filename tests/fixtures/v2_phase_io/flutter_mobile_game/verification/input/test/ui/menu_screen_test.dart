/// Tests for MenuScreen — splash screen + main menu navigation.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:magic_tower/ui/menu_screen.dart';

void main() {
  group('MenuScreen', () {
    /// Build the menu screen in a test widget tree.
    Widget _buildTestableWidget({
      required VoidCallback onNewGame,
      required VoidCallback onContinue,
      required VoidCallback onSettings,
      required VoidCallback onAbout,
    }) {
      return MaterialApp(
        home: MenuScreen(
          onNewGame: onNewGame,
          onContinue: onContinue,
          onSettings: onSettings,
          onAbout: onAbout,
        ),
      );
    }

    testWidgets('shows splash screen on first frame', (tester) async {
      await tester.pumpWidget(_buildTestableWidget(
        onNewGame: () {},
        onContinue: () {},
        onSettings: () {},
        onAbout: () {},
      ));

      // Should show splash (black background, title text).
      expect(find.byType(Scaffold), findsOneWidget);
      expect(find.text('魔塔'), findsOneWidget);
      expect(find.text('Magic Tower'), findsOneWidget);
    });

    testWidgets('transitions to main menu after splash duration', (tester) async {
      await tester.pumpWidget(_buildTestableWidget(
        onNewGame: () {},
        onContinue: () {},
        onSettings: () {},
        onAbout: () {},
      ));

      // Wait for splash to complete.
      await tester.pumpAndSettle();

      // Should show main menu with buttons.
      expect(find.text('开始游戏'), findsOneWidget);
      expect(find.text('New Game'), findsOneWidget);
      expect(find.text('继续游戏'), findsOneWidget);
      expect(find.text('Continue'), findsOneWidget);
      expect(find.text('设置'), findsOneWidget);
      expect(find.text('Settings'), findsOneWidget);
      expect(find.text('关于'), findsOneWidget);
      expect(find.text('About'), findsOneWidget);
    });

    testWidgets('onNewGame callback fires', (tester) async {
      var newGameCalled = false;
      await tester.pumpWidget(_buildTestableWidget(
        onNewGame: () => newGameCalled = true,
        onContinue: () {},
        onSettings: () {},
        onAbout: () {},
      ));

      await tester.pumpAndSettle();
      await tester.tap(find.text('开始游戏'));
      expect(newGameCalled, isTrue);
    });

    testWidgets('onContinue callback fires', (tester) async {
      var continueCalled = false;
      await tester.pumpWidget(_buildTestableWidget(
        onNewGame: () {},
        onContinue: () => continueCalled = true,
        onSettings: () {},
        onAbout: () {},
      ));

      await tester.pumpAndSettle();
      await tester.tap(find.text('继续游戏'));
      expect(continueCalled, isTrue);
    });

    testWidgets('onSettings callback fires', (tester) async {
      var settingsCalled = false;
      await tester.pumpWidget(_buildTestableWidget(
        onNewGame: () {},
        onContinue: () {},
        onSettings: () => settingsCalled = true,
        onAbout: () {},
      ));

      await tester.pumpAndSettle();
      await tester.tap(find.text('设置'));
      expect(settingsCalled, isTrue);
    });

    testWidgets('onAbout callback fires', (tester) async {
      var aboutCalled = false;
      await tester.pumpWidget(_buildTestableWidget(
        onNewGame: () {},
        onContinue: () {},
        onSettings: () {},
        onAbout: () => aboutCalled = true,
      ));

      await tester.pumpAndSettle();
      await tester.tap(find.text('关于'));
      expect(aboutCalled, isTrue);
    });

    test('MenuAction enum has expected values', () {
      expect(MenuAction.values, contains(MenuAction.start));
      expect(MenuAction.values, contains(MenuAction.continueGame));
      expect(MenuAction.values, contains(MenuAction.settings));
      expect(MenuAction.values, contains(MenuAction.about));
      expect(MenuAction.values.length, 4);
    });
  });
}
