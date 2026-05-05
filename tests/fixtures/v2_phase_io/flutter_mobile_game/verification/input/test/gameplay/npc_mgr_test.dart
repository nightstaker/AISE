import 'package:magic_tower/gameplay/npc_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('NPCMgr', () {
    late NPCMgr npcMgr;

    setUp(() {
      npcMgr = NPCMgr();
      npcMgr.initialize();
    });

    group('initialization', () {
      test('isInitialized returns true', () {
        expect(npcMgr.isInitialized, isTrue);
      });

      test('dialogueCount returns 0', () {
        expect(npcMgr.dialogueCount, equals(0));
      });

      test('hasNPC returns false initially', () {
        expect(npcMgr.hasNPC('wizard'), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.hasNPC('test'), throwsStateError);
      });
    });

    group('addNPC', () {
      test('adds NPC with dialogue', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello, brave adventurer.'], nextPage: 1),
          DialoguePage(lines: ['The tower holds many secrets.'], nextPage: null),
        ]);
        expect(npcMgr.hasNPC('wizard'), isTrue);
      });

      test('adds NPC without dialogue', () {
        npcMgr.addNPC('guard', 'Guard');
        expect(npcMgr.hasNPC('guard'), isTrue);
      });

      test('updates existing NPC', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello'], nextPage: null),
        ]);
        npcMgr.addNPC('wizard', 'Wizard Updated', [
          DialoguePage(lines: ['New dialogue'], nextPage: null),
        ]);
        expect(npcMgr.getNPCName('wizard'), equals('Wizard Updated'));
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(
          () => fresh.addNPC('test', 'Test NPC'),
          throwsStateError,
        );
      });
    });

    group('removeNPC', () {
      test('removes NPC with dialogue', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello'], nextPage: null),
        ]);
        final removed = npcMgr.removeNPC('wizard');
        expect(removed, isTrue);
        expect(npcMgr.hasNPC('wizard'), isFalse);
      });

      test('returns false for non-existent NPC', () {
        final removed = npcMgr.removeNPC('nonexistent');
        expect(removed, isFalse);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.removeNPC('test'), throwsStateError);
      });
    });

    group('getNPCName', () {
      test('returns NPC name', () {
        npcMgr.addNPC('wizard', 'Wizard');
        expect(npcMgr.getNPCName('wizard'), equals('Wizard'));
      });

      test('returns null for non-existent NPC', () {
        expect(npcMgr.getNPCName('nonexistent'), isNull);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.getNPCName('test'), throwsStateError);
      });
    });

    group('startDialogue', () {
      test('starts dialogue for NPC with dialogue', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello, adventurer.'], nextPage: 1),
          DialoguePage(lines: ['Take care in the tower.'], nextPage: null),
        ]);
        final result = npcMgr.startDialogue('wizard');
        expect(result, isTrue);
        expect(npcMgr.currentPage, equals(0));
        expect(npcMgr.currentNPCId, equals('wizard'));
      });

      test('returns false for NPC without dialogue', () {
        npcMgr.addNPC('guard', 'Guard');
        final result = npcMgr.startDialogue('guard');
        expect(result, isFalse);
      });

      test('returns false for non-existent NPC', () {
        final result = npcMgr.startDialogue('nonexistent');
        expect(result, isFalse);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.startDialogue('test'), throwsStateError);
      });
    });

    group('nextPage', () {
      test('advances to next page', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Page 1'], nextPage: 1),
          DialoguePage(lines: ['Page 2'], nextPage: null),
        ]);
        npcMgr.startDialogue('wizard');
        npcMgr.nextPage();
        expect(npcMgr.currentPage, equals(1));
      });

      test('stays on last page', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Page 1'], nextPage: null),
        ]);
        npcMgr.startDialogue('wizard');
        npcMgr.nextPage();
        expect(npcMgr.currentPage, equals(0));
      });

      test('does nothing when no dialogue', () {
        npcMgr.nextPage();
        expect(npcMgr.currentPage, equals(-1));
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.nextPage(), throwsStateError);
      });
    });

    group('getLines', () {
      test('returns lines for current page', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello', 'World'], nextPage: 1),
          DialoguePage(lines: ['Goodbye'], nextPage: null),
        ]);
        npcMgr.startDialogue('wizard');
        expect(npcMgr.getLines(), equals(['Hello', 'World']));
      });

      test('returns empty when no dialogue', () {
        expect(npcMgr.getLines(), isEmpty);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.getLines(), throwsStateError);
      });
    });

    group('isOnDialogue', () {
      test('returns true when on dialogue', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello'], nextPage: null),
        ]);
        npcMgr.startDialogue('wizard');
        expect(npcMgr.isOnDialogue(), isTrue);
      });

      test('returns false when not on dialogue', () {
        expect(npcMgr.isOnDialogue(), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.isOnDialogue(), throwsStateError);
      });
    });

    group('endDialogue', () {
      test('ends current dialogue', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello'], nextPage: null),
        ]);
        npcMgr.startDialogue('wizard');
        npcMgr.endDialogue();
        expect(npcMgr.currentPage, equals(-1));
        expect(npcMgr.currentNPCId, isNull);
      });

      test('does nothing when no dialogue', () {
        npcMgr.endDialogue();
        expect(npcMgr.currentPage, equals(-1));
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.endDialogue(), throwsStateError);
      });
    });

    group('hasClue', () {
      test('returns true for added clue', () {
        npcMgr.addClue('secret_passage', 'There is a secret passage behind the waterfall.');
        expect(npcMgr.hasClue('secret_passage'), isTrue);
      });

      test('returns false for non-existent clue', () {
        expect(npcMgr.hasClue('nonexistent'), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.hasClue('test'), throwsStateError);
      });
    });

    group('addClue', () {
      test('adds clue with text', () {
        npcMgr.addClue('secret_passage', 'Behind the waterfall.');
        expect(npcMgr.getClueText('secret_passage'), equals('Behind the waterfall.'));
      });

      test('updates existing clue', () {
        npcMgr.addClue('secret', 'Old text');
        npcMgr.addClue('secret', 'New text');
        expect(npcMgr.getClueText('secret'), equals('New text'));
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.addClue('test', 'Text'), throwsStateError);
      });
    });

    group('getClueText', () {
      test('returns clue text', () {
        npcMgr.addClue('secret', 'Hidden text');
        expect(npcMgr.getClueText('secret'), equals('Hidden text'));
      });

      test('returns null for non-existent clue', () {
        expect(npcMgr.getClueText('nonexistent'), isNull);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.getClueText('test'), throwsStateError);
      });
    });

    group('getClueCount', () {
      test('returns number of clues', () {
        npcMgr.addClue('clue1', 'Text 1');
        npcMgr.addClue('clue2', 'Text 2');
        expect(npcMgr.clueCount, equals(2));
      });

      test('returns 0 when no clues', () {
        expect(npcMgr.clueCount, equals(0));
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.clueCount, throwsStateError);
      });
    });

    group('getClues', () {
      test('returns all clues', () {
        npcMgr.addClue('clue1', 'Text 1');
        npcMgr.addClue('clue2', 'Text 2');
        final clues = npcMgr.getClues();
        expect(clues.length, equals(2));
        expect(clues['clue1'], equals('Text 1'));
        expect(clues['clue2'], equals('Text 2'));
      });

      test('returns empty map when no clues', () {
        expect(npcMgr.getClues(), isEmpty);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.getClues(), throwsStateError);
      });
    });

    group('clearAll', () {
      test('clears all NPCs, dialogues, and clues', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello'], nextPage: null),
        ]);
        npcMgr.addClue('secret', 'Hidden');
        npcMgr.startDialogue('wizard');
        npcMgr.clearAll();
        expect(npcMgr.hasNPC('wizard'), isFalse);
        expect(npcMgr.hasClue('secret'), isFalse);
        expect(npcMgr.isOnDialogue(), isFalse);
      });

      test('throws when not initialized', () {
        final fresh = NPCMgr();
        expect(() => fresh.clearAll(), throwsStateError);
      });
    });

    group('toJson / fromJson', () {
      test('serializes and deserializes correctly', () {
        npcMgr.addNPC('wizard', 'Wizard', [
          DialoguePage(lines: ['Hello'], nextPage: null),
        ]);
        npcMgr.addClue('secret', 'Hidden passage');

        final json = npcMgr.toJson();
        final restored = NPCMgr.fromJson(json);
        restored.initialize();

        expect(restored.hasNPC('wizard'), isTrue);
        expect(restored.getNPCName('wizard'), equals('Wizard'));
        expect(restored.hasClue('secret'), isTrue);
        expect(restored.getClueText('secret'), equals('Hidden passage'));
      });
    });
  });
}
