/// E2E scenario: npc_dialogue
///
/// Trigger: {"action": "move", "target": "npc_tile"}
/// Effect: {"dialogue_shown": true, "pages_available": 3, "has_hint": true}
///
/// Validates NPC dialogue: multi-page story text with hints, page navigation.

import 'package:magic_tower/gameplay/npc_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('NPC Dialogue — E2E Scenario', () {
    late NPCMgr npcMgr;

    setUp(() {
      npcMgr = NPCMgr();
      npcMgr.initialize();

      // Add an NPC with 3 pages of dialogue including a hint
      npcMgr.addNPC(
        'wise_mage',
        'Wise Old Mage',
        [
          DialoguePage(
            lines: [
              'Welcome, brave adventurer.',
              'The tower holds many secrets.',
            ],
            nextPage: 1,
          ),
          DialoguePage(
            lines: [
              'Beware the guardian on floor 10.',
              'He has two forms — be prepared.',
            ],
            nextPage: 2,
          ),
          DialoguePage(
            lines: [
              'Here is a hint: the red gem on floor 3',
              'will help you defeat the boss.',
            ],
            nextPage: null,
          ),
        ],
      );
    });

    test('start dialogue: NPC name shown, page 1 displayed', () {
      final started = npcMgr.startDialogue('wise_mage');
      expect(started, isTrue);
      expect(npcMgr.currentNPCId, equals('wise_mage'));
      expect(npcMgr.currentPage, equals(0));
      expect(npcMgr.isOnDialogue(), isTrue);

      final lines = npcMgr.getLines();
      expect(lines, hasLength(2));
      expect(lines[0], equals('Welcome, brave adventurer.'));
      expect(lines[1], equals('The tower holds many secrets.'));
    });

    test('page navigation: 3 pages available, can navigate between them',
        () {
      npcMgr.startDialogue('wise_mage');

      // Page 1
      var lines = npcMgr.getLines();
      expect(lines[0], contains('Welcome'));

      // Go to page 2
      npcMgr.nextPage();
      expect(npcMgr.currentPage, equals(1));
      lines = npcMgr.getLines();
      expect(lines[0], contains('Beware'));

      // Go to page 3
      npcMgr.nextPage();
      expect(npcMgr.currentPage, equals(2));
      lines = npcMgr.getLines();
      expect(lines[0], contains('hint'));

      // Verify hint is present
      final hasHint = lines.any((l) => l.toLowerCase().contains('hint'));
      expect(hasHint, isTrue);
    });

    test('end dialogue: resets state', () {
      npcMgr.startDialogue('wise_mage');
      expect(npcMgr.isOnDialogue(), isTrue);

      npcMgr.endDialogue();
      expect(npcMgr.isOnDialogue(), isFalse);
      expect(npcMgr.currentNPCId, isNull);
      expect(npcMgr.currentPage, equals(-1));
    });

    test('non-existent NPC returns false', () {
      final started = npcMgr.startDialogue('unknown_npc');
      expect(started, isFalse);
      expect(npcMgr.isOnDialogue(), isFalse);
    });

    test('NPC with empty dialogues cannot be started', () {
      npcMgr.addNPC('empty_npc', 'Silent NPC', []);
      final started = npcMgr.startDialogue('empty_npc');
      expect(started, isFalse);
    });

    test('clue management: add and retrieve clues', () {
      npcMgr.addClue('floor3_secret', 'Red gem is behind the wall');
      expect(npcMgr.clueCount, equals(1));

      npcMgr.addClue('boss_weakness', 'Boss is weak to blue gems');
      expect(npcMgr.clueCount, equals(2));
    });

    test('dialogue count reflects number of NPCs', () {
      expect(npcMgr.dialogueCount, equals(1));

      npcMgr.addNPC('shopkeeper', 'Shopkeeper', [
        DialoguePage(lines: ['Welcome!'], nextPage: null),
      ]);
      expect(npcMgr.dialogueCount, equals(2));
    });

    test('removing NPC clears dialogue state', () {
      npcMgr.startDialogue('wise_mage');
      expect(npcMgr.isOnDialogue(), isTrue);

      final removed = npcMgr.removeNPC('wise_mage');
      expect(removed, isTrue);
      expect(npcMgr.isOnDialogue(), isFalse);
      expect(npcMgr.currentNPCId, isNull);
    });
  });
}
