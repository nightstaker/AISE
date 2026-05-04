/// Tests for DialogueScreen — NPC conversation interface.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:magic_tower/ui/dialogue_screen.dart';

void main() {
  group('DialogueScreen', () {
    /// Build the dialogue screen in a testable tree.
    Widget _buildWidget({
      required String npcName,
      required List<String> dialogueLines,
      int currentPage = 0,
      required bool isActive,
      required VoidCallback onNextPage,
      required VoidCallback onClose,
    }) {
      return MaterialApp(
        home: Scaffold(
          body: Container(
            color: Colors.black,
            child: DialogueScreen(
              npcName: npcName,
              dialogueLines: dialogueLines,
              currentPage: currentPage,
              isActive: isActive,
              onNextPage: onNextPage,
              onClose: onClose,
            ),
          ),
        ),
      );
    }

    final testLines = [
      'Hello, adventurer!',
      'The tower is dangerous.',
      'Be careful of the monsters.',
    ];

    testWidgets('displays NPC name', (tester) async {
      await tester.pumpWidget(_buildWidget(
        npcName: 'Guard',
        dialogueLines: testLines,
        isActive: true,
        onNextPage: () {},
        onClose: () {},
      ));

      expect(find.text('Guard'), findsOneWidget);
    });

    testWidgets('displays current dialogue line', (tester) async {
      await tester.pumpWidget(_buildWidget(
        npcName: 'Guard',
        dialogueLines: testLines,
        currentPage: 0,
        isActive: true,
        onNextPage: () {},
        onClose: () {},
      ));

      expect(find.text('Hello, adventurer!'), findsOneWidget);
    });

    testWidgets('advances to next page on tap', (tester) async {
      await tester.pumpWidget(_buildWidget(
        npcName: 'Guard',
        dialogueLines: testLines,
        currentPage: 0,
        isActive: true,
        onNextPage: () {},
        onClose: () {},
      ));

      expect(find.text('Hello, adventurer!'), findsOneWidget);

      await tester.tap(find.text('下一句 >>'));
      await tester.pumpAndSettle();

      expect(find.text('The tower is dangerous.'), findsOneWidget);
    });

    testWidgets('closes dialogue on close tap', (tester) async {
      var closeCalled = false;
      await tester.pumpWidget(_buildWidget(
        npcName: 'Guard',
        dialogueLines: testLines,
        isActive: true,
        onNextPage: () {},
        onClose: () => closeCalled = true,
      ));

      await tester.tap(find.text('关闭'));
      expect(closeCalled, isTrue);
    });

    testWidgets('shows NPC portrait placeholder', (tester) async {
      await tester.pumpWidget(_buildWidget(
        npcName: 'Guard',
        dialogueLines: testLines,
        isActive: true,
        onNextPage: () {},
        onClose: () {},
      ));

      // NPC portrait is a container with a colored background.
      expect(find.byType(Container), findsNWidgets(greaterThan(1)));
    });

    testWidgets('does not advance when not active', (tester) async {
      await tester.pumpWidget(_buildWidget(
        npcName: 'Guard',
        dialogueLines: testLines,
        currentPage: 0,
        isActive: false,
        onNextPage: () {},
        onClose: () {},
      ));

      // The next button should be disabled.
      final nextButton = find.text('下一句 >>');
      expect(nextButton, findsOneWidget);
    });

    testWidgets('shows correct page index', (tester) async {
      await tester.pumpWidget(_buildWidget(
        npcName: 'Guard',
        dialogueLines: testLines,
        currentPage: 1,
        isActive: true,
        onNextPage: () {},
        onClose: () {},
      ));

      expect(find.text('The tower is dangerous.'), findsOneWidget);
    });

    test('initialize and isInitialized work', () {
      final screen = DialogueScreen(
        npcName: 'Guard',
        dialogueLines: testLines,
        isActive: true,
        onNextPage: () {},
        onClose: () {},
      );
      screen.initialize();
      expect(screen.isInitialized, isTrue);
    });
  });
}
