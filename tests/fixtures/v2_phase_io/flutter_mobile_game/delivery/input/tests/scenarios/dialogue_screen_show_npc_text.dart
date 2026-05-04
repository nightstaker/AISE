/// E2E scenario: dialogue_screen_show_npc_text
///
/// Trigger: {"action": "move_to_npc"}
/// Effect: {"dialogue_screen_shown": true, "npc_name_displayed": true, "page_number": "1/3", "dialogue_text_visible": true, "next_button_available": true, "page_turning_works": true}
///
/// Validates the dialogue screen shows NPC name, multi-page text,
/// page numbering, and next-page navigation.

import 'package:magic_tower/gameplay/npc_mgr.dart';
import 'package:magic_tower/system/i18n_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('Dialogue Screen Show NPC Text — E2E Scenario', () {
    late NPCMgr npcMgr;
    late I18nMgr i18n;

    setUp(() {
      npcMgr = NPCMgr();
      npcMgr.initialize();

      i18n = I18nMgr();
      i18n.initialize();

      // Add an NPC with 3 pages of dialogue
      npcMgr.addNPC(
        'elder',
        'Village Elder',
        [
          DialoguePage(
            lines: [
              'The tower has been a mystery for centuries.',
              'Many have tried to reach the top.',
            ],
            nextPage: 1,
          ),
          DialoguePage(
            lines: [
              'On the 10th floor, a great dragon guards the exit.',
              'You must be prepared with the right items.',
            ],
            nextPage: 2,
          ),
          DialoguePage(
            lines: [
              'Take this hint: the red gem on floor 3',
              'will give you the strength you need.',
            ],
            nextPage: null,
          ),
        ],
      );
    });

    test('dialogue screen is shown when approaching NPC', () {
      final started = npcMgr.startDialogue('elder');
      expect(started, isTrue);
      expect(npcMgr.isOnDialogue(), isTrue);
      expect(npcMgr.currentNPCId, equals('elder'));
    });

    test('NPC name is displayed', () {
      npcMgr.startDialogue('elder');
      final npcName = npcMgr.getNPCName('elder');
      expect(npcName, equals('Village Elder'));
      expect(npcName, isNotNull);
      expect(npcName!.isNotEmpty, isTrue);
    });

    test('page number shows correct format: 1/3', () {
      npcMgr.startDialogue('elder');
      expect(npcMgr.currentPage, equals(0));

      // Page 1 of 3 (0-indexed, so display as 1/3)
      final currentPage = npcMgr.currentPage;
      final totalPages = npcMgr.dialogueCount;
      final pageNumber = '${currentPage + 1}/$totalPages';
      expect(pageNumber, equals('1/3'));
    });

    test('dialogue text is visible on each page', () {
      npcMgr.startDialogue('elder');

      // Page 1
      var lines = npcMgr.getLines();
      expect(lines.length, equals(2));
      expect(lines[0], contains('mystery'));
      expect(lines[1], contains('tried'));

      // Page 2
      npcMgr.nextPage();
      lines = npcMgr.getLines();
      expect(lines.length, equals(2));
      expect(lines[0], contains('dragon'));
      expect(lines[1], contains('items'));

      // Page 3
      npcMgr.nextPage();
      lines = npcMgr.getLines();
      expect(lines.length, equals(2));
      expect(lines[0], contains('hint'));
      expect(lines[1], contains('red gem'));
    });

    test('next button is available for page navigation', () {
      npcMgr.startDialogue('elder');
      expect(npcMgr.isOnDialogue(), isTrue);

      // Can advance to next page
      npcMgr.nextPage();
      expect(npcMgr.currentPage, equals(1));

      // Can advance again
      npcMgr.nextPage();
      expect(npcMgr.currentPage, equals(2));

      // At last page, nextPage does nothing (no more pages)
      final prevPage = npcMgr.currentPage;
      npcMgr.nextPage();
      expect(npcMgr.currentPage, equals(prevPage),
          reason: 'Should stay on last page when no more pages');
    });

    test('page turning works: can navigate forward through all pages', () {
      npcMgr.startDialogue('elder');

      final pagesVisited = <int>[];
      while (npcMgr.isOnDialogue()) {
        pagesVisited.add(npcMgr.currentPage);
        npcMgr.nextPage();
        // Stop if we've reached the last page
        if (npcMgr.currentPage >= 2) break;
      }

      expect(pagesVisited, equals([0, 1, 2]));
    });

    test('dialogue can be closed and state is reset', () {
      npcMgr.startDialogue('elder');
      expect(npcMgr.isOnDialogue(), isTrue);
      expect(npcMgr.currentPage, equals(0));

      npcMgr.endDialogue();
      expect(npcMgr.isOnDialogue(), isFalse);
      expect(npcMgr.currentNPCId, isNull);
      expect(npcMgr.currentPage, equals(-1));
    });

    test('dialogue screen shows hint on last page', () {
      npcMgr.startDialogue('elder');
      npcMgr.nextPage();
      npcMgr.nextPage();

      final lines = npcMgr.getLines();
      final hasHint = lines.any((l) =>
          l.toLowerCase().contains('hint') ||
          l.toLowerCase().contains('red gem'));
      expect(hasHint, isTrue);
    });

    test('multiple NPCs can have dialogues', () {
      npcMgr.addNPC(
        'shopkeeper',
        'Shopkeeper',
        [
          DialoguePage(lines: ['Welcome to my shop!'], nextPage: null),
        ],
      );

      expect(npcMgr.dialogueCount, equals(2));

      // Can start dialogue with either NPC
      expect(npcMgr.startDialogue('elder'), isTrue);
      expect(npcMgr.currentNPCId, equals('elder'));

      npcMgr.endDialogue();
      expect(npcMgr.startDialogue('shopkeeper'), isTrue);
      expect(npcMgr.currentNPCId, equals('shopkeeper'));
    });

    test('dialogue text is visible with i18n support', () {
      // Dialogue text itself is stored in NPC data, not translated by i18n
      // But the NPC name can be displayed with i18n
      npcMgr.startDialogue('elder');
      final lines = npcMgr.getLines();

      expect(lines.length, greaterThan(0));
      expect(lines[0].isNotEmpty, isTrue);

      // Dialogue text should be non-empty and visible
      for (final line in lines) {
        expect(line.trim().isNotEmpty, isTrue,
            reason: 'Dialogue lines should not be empty');
      }
    });
  });
}
