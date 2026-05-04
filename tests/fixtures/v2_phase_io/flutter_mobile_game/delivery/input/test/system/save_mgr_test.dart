/// Save Manager Tests — 自动存档/手动存档 JSON 文件读写
///
/// Covers:
/// - Initialization guards (StateError when not initialised)
/// - Auto-save roundtrip, overwrite, delete, hasAutoSave
/// - SaveState toJson / fromJson (roundtrip, missing fields)
/// - Manual save: save, load, overwrite, delete, hasSave, out-of-range
/// - listSaveSlots, getSaveMetadata
/// - clearAllSaves, clearAll
/// - Invalid slot handling

import 'package:magic_tower/system/save_mgr.dart';
import 'package:magic_tower/data/models.dart';
import 'package:test/test.dart';

void main() {
  // ──────────────────────────────────────────────────────────────────────
  // Initialization
  // ──────────────────────────────────────────────────────────────────────

  group('Initialization', () {
    test('not initialized by default', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.isInitialized, isFalse);
    });

    test('can be initialized', () {
      final saveMgr = SaveMgr();
      saveMgr.initialize();
      expect(saveMgr.isInitialized, isTrue);
    });

    test('throws StateError when not initialized — autoSave', () {
      final saveMgr = SaveMgr();
      expect(
        () => saveMgr.autoSave(
          playerState: PlayerState(
            hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
          ),
          currentFloor: 1,
        ),
        throwsStateError,
      );
    });

    test('throws StateError when not initialized — loadAutoSave', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.loadAutoSave(), throwsStateError);
    });

    test('throws StateError when not initialized — hasAutoSave', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.hasAutoSave(), throwsStateError);
    });

    test('throws StateError when not initialized — manualSave', () {
      final saveMgr = SaveMgr();
      expect(
        () => saveMgr.manualSave(
          1,
          PlayerState(
            hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
          ),
          1,
        ),
        throwsStateError,
      );
    });

    test('throws StateError when not initialized — loadSave', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.loadSave(1), throwsStateError);
    });

    test('throws StateError when not initialized — deleteSave', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.deleteSave(1), throwsStateError);
    });

    test('throws StateError when not initialized — deleteAutoSave', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.deleteAutoSave(), throwsStateError);
    });

    test('throws StateError when not initialized — clearAllSaves', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.clearAllSaves(), throwsStateError);
    });

    test('throws StateError when not initialized — clearAll', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.clearAll(), throwsStateError);
    });

    test('throws StateError when not initialized — listSaveSlots', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.listSaveSlots(), throwsStateError);
    });

    test('throws StateError when not initialized — hasSave', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.hasSave(1), throwsStateError);
    });

    test('throws StateError when not initialized — getSaveMetadata', () {
      final saveMgr = SaveMgr();
      expect(saveMgr.getSaveMetadata(1), throwsStateError);
    });
  });

  // ──────────────────────────────────────────────────────────────────────
  // Auto-save
  // ──────────────────────────────────────────────────────────────────────

  group('AutoSave', () {
    late SaveMgr saveMgr;

    setUp(() {
      saveMgr = SaveMgr();
      saveMgr.initialize();
    });

    test('autoSave and loadAutoSave roundtrip', () async {
      final state = PlayerState(
        hp: 100, maxHp: 100, atk: 10, def: 8, gold: 200, exp: 500, level: 3,
      );
      await saveMgr.autoSave(
        playerState: state,
        currentFloor: 5,
      );

      final loaded = await saveMgr.loadAutoSave();
      expect(loaded, isNotNull);
      expect(loaded!.currentFloor, 5);
      expect(loaded.playerState.hp, 100);
      expect(loaded.playerState.atk, 10);
      expect(loaded.playerState.def, 8);
      expect(loaded.playerState.gold, 200);
      expect(loaded.playerState.exp, 500);
      expect(loaded.playerState.level, 3);
      expect(loaded.timestamp, isNotEmpty);
    });

    test('loadAutoSave returns null when no file exists', () async {
      final result = await saveMgr.loadAutoSave();
      expect(result, isNull);
    });

    test('hasAutoSave is false when no file exists', () async {
      expect(await saveMgr.hasAutoSave(), isFalse);
    });

    test('hasAutoSave is true after save', () async {
      await saveMgr.autoSave(
        playerState: PlayerState(
          hp: 50, maxHp: 50, atk: 5, def: 5, gold: 10, exp: 0, level: 1,
        ),
        currentFloor: 1,
      );
      expect(await saveMgr.hasAutoSave(), isTrue);
    });

    test('autoSave overwrites previous auto-save', () async {
      await saveMgr.autoSave(
        playerState: PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        currentFloor: 1,
      );

      await saveMgr.autoSave(
        playerState: PlayerState(
          hp: 80, maxHp: 100, atk: 8, def: 6, gold: 100, exp: 200, level: 2,
        ),
        currentFloor: 3,
      );

      final loaded = await saveMgr.loadAutoSave();
      expect(loaded!.currentFloor, 3);
      expect(loaded.playerState.hp, 80);
      expect(loaded.playerState.level, 2);
    });

    test('autoSave with bossDefeated and npcTriggered', () async {
      await saveMgr.autoSave(
        playerState: PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        currentFloor: 1,
        bossDefeated: {'boss1'},
        npcTriggered: {'npc_guide'},
        inventory: {'key_red'},
      );

      final loaded = await saveMgr.loadAutoSave();
      expect(loaded!.bossDefeated, contains('boss1'));
      expect(loaded.npcTriggered, contains('npc_guide'));
      expect(loaded.inventory, contains('key_red'));
    });

    test('deleteAutoSave removes the file', () async {
      await saveMgr.autoSave(
        playerState: PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        currentFloor: 1,
      );
      expect(await saveMgr.hasAutoSave(), isTrue);

      await saveMgr.deleteAutoSave();
      expect(await saveMgr.hasAutoSave(), isFalse);
      expect(await saveMgr.loadAutoSave(), isNull);
    });

    test('SaveState toJson / fromJson roundtrip', () {
      final state = SaveState(
        currentFloor: 7,
        playerState: PlayerState(
          hp: 200, maxHp: 200, atk: 15, def: 10, gold: 300, exp: 800, level: 5,
        ),
        timestamp: '2025-01-01T00:00:00.000Z',
        bossDefeated: {'boss_lord'},
        npcTriggered: {'npc_queen'},
        inventory: {'gem_red', 'potion_blue'},
      );

      final json = state.toJson();
      expect(json['floor'], 7);
      expect(json['player']['hp'], 200);
      expect(json['bossDefeated'], ['boss_lord']);
      expect(json['npcTriggered'], ['npc_queen']);
      expect(json['inventory'], ['gem_red', 'potion_blue']);

      final restored = SaveState.fromJson(json);
      expect(restored, state);
    });

    test('SaveState.fromJson handles missing optional fields', () {
      final json = {
        'floor': 1,
        'player': {
          'hp': 100, 'maxHp': 100, 'atk': 5, 'def': 5,
          'gold': 0, 'exp': 0, 'level': 1,
        },
        'timestamp': '2025-01-01T00:00:00.000Z',
      };
      final state = SaveState.fromJson(json);
      expect(state.bossDefeated, isEmpty);
      expect(state.npcTriggered, isEmpty);
      expect(state.inventory, isEmpty);
    });
  });

  // ──────────────────────────────────────────────────────────────────────
  // Manual save / load
  // ──────────────────────────────────────────────────────────────────────

  group('ManualSave', () {
    late SaveMgr saveMgr;

    setUp(() {
      saveMgr = SaveMgr();
      saveMgr.initialize();
    });

    test('save and load game state', () async {
      final state = PlayerState(
        hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 2,
      );
      await saveMgr.manualSave(1, state, 1);

      final loaded = await saveMgr.loadSave(1);

      expect(loaded, isNotNull);
      expect(loaded!.hp, 100);
      expect(loaded.gold, 50);
      expect(loaded.level, 2);
    });

    test('load from empty slot returns null', () async {
      final loaded = await saveMgr.loadSave(99);
      expect(loaded, isNull);
    });

    test('slot index out of range returns null', () async {
      expect(await saveMgr.loadSave(0), isNull);
      expect(await saveMgr.loadSave(100), isNull);
    });

    test('multiple slots are independent', () async {
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        1,
      );
      await saveMgr.manualSave(
        2,
        PlayerState(
          hp: 200, maxHp: 200, atk: 10, def: 10, gold: 100, exp: 200, level: 2,
        ),
        5,
      );

      final s1 = await saveMgr.loadSave(1);
      final s2 = await saveMgr.loadSave(2);

      expect(s1!.hp, 100);
      expect(s1.currentFloor, 1);
      expect(s2!.hp, 200);
      expect(s2.currentFloor, 5);
    });

    test('manualSave overwrites existing slot', () async {
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 50, maxHp: 50, atk: 3, def: 3, gold: 10, exp: 0, level: 1,
        ),
        1,
      );

      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 2,
        ),
        3,
      );

      final loaded = await saveMgr.loadSave(1);
      expect(loaded!.hp, 100);
      expect(loaded.currentFloor, 3);
      expect(loaded.level, 2);
    });

    test('invalid slot throws ArgumentError', () async {
      final state = PlayerState(
        hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
      );
      expect(() => saveMgr.manualSave(0, state, 1), throwsArgumentError);
      expect(
        () => saveMgr.manualSave(100, state, 1),
        throwsArgumentError,
      );
    });

    test('hasSave returns correct values', () async {
      expect(await saveMgr.hasSave(1), isFalse);
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        1,
      );
      expect(await saveMgr.hasSave(1), isTrue);
      expect(await saveMgr.hasSave(2), isFalse);
    });

    test('hasSave returns false for out-of-range slot', () async {
      expect(await saveMgr.hasSave(0), isFalse);
      expect(await saveMgr.hasSave(100), isFalse);
    });

    test('deleteSave removes the slot', () async {
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        1,
      );
      expect(await saveMgr.hasSave(1), isTrue);

      await saveMgr.deleteSave(1);
      expect(await saveMgr.hasSave(1), isFalse);
      expect(await saveMgr.loadSave(1), isNull);
    });

    test('deleteSave on non-existent slot does nothing', () async {
      expect(() => saveMgr.deleteSave(99), returnsNormally);
    });

    test('deleteSave on out-of-range slot does nothing', () async {
      expect(() => saveMgr.deleteSave(0), returnsNormally);
      expect(() => saveMgr.deleteSave(100), returnsNormally);
    });

    test('getSaveMetadata returns correct data', () async {
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 80, maxHp: 100, atk: 8, def: 6, gold: 120, exp: 300, level: 4,
        ),
        7,
      );

      final meta = await saveMgr.getSaveMetadata(1);
      expect(meta, isNotNull);
      expect(meta!['floor'], 7);
      expect(meta['level'], 4);
      expect(meta['hp'], 80);
      expect(meta['timestamp'], isNotEmpty);
    });

    test('getSaveMetadata returns null for empty slot', () async {
      expect(await saveMgr.getSaveMetadata(99), isNull);
    });
  });

  // ──────────────────────────────────────────────────────────────────────
  // listSaveSlots
  // ──────────────────────────────────────────────────────────────────────

  group('ListSaveSlots', () {
    late SaveMgr saveMgr;

    setUp(() {
      saveMgr = SaveMgr();
      saveMgr.initialize();
    });

    test('empty slots returns empty map', () async {
      final slots = await saveMgr.listSaveSlots();
      expect(slots, isEmpty);
    });

    test('listSaveSlots lists all occupied slots', () async {
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        1,
      );
      await saveMgr.manualSave(
        3,
        PlayerState(
          hp: 200, maxHp: 200, atk: 10, def: 10, gold: 100, exp: 200, level: 2,
        ),
        5,
      );

      final slots = await saveMgr.listSaveSlots();
      expect(slots.length, 2);
      expect(slots.containsKey(1), isTrue);
      expect(slots.containsKey(3), isTrue);
      expect(slots[1]!.currentFloor, 1);
      expect(slots[3]!.currentFloor, 5);
    });

    test('listSaveSlots skips empty slots', () async {
      await saveMgr.manualSave(
        2,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        1,
      );

      final slots = await saveMgr.listSaveSlots();
      expect(slots.length, 1);
      expect(slots.containsKey(2), isTrue);
      expect(slots.containsKey(1), isFalse);
      expect(slots.containsKey(3), isFalse);
    });
  });

  // ──────────────────────────────────────────────────────────────────────
  // Clear all
  // ──────────────────────────────────────────────────────────────────────

  group('ClearAll', () {
    late SaveMgr saveMgr;

    setUp(() {
      saveMgr = SaveMgr();
      saveMgr.initialize();
    });

    test('clearAllSaves removes all manual saves', () async {
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        1,
      );
      await saveMgr.manualSave(
        2,
        PlayerState(
          hp: 200, maxHp: 200, atk: 10, def: 10, gold: 100, exp: 200, level: 2,
        ),
        3,
      );

      await saveMgr.clearAllSaves();

      expect(await saveMgr.hasSave(1), isFalse);
      expect(await saveMgr.hasSave(2), isFalse);
      expect(await saveMgr.listSaveSlots(), isEmpty);
    });

    test('clearAll removes auto-save and all manual saves', () async {
      await saveMgr.autoSave(
        playerState: PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        currentFloor: 1,
      );
      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 200, maxHp: 200, atk: 10, def: 10, gold: 100, exp: 200, level: 2,
        ),
        3,
      );

      await saveMgr.clearAll();

      expect(await saveMgr.hasAutoSave(), isFalse);
      expect(await saveMgr.hasSave(1), isFalse);
      expect(await saveMgr.loadAutoSave(), isNull);
      expect(await saveMgr.listSaveSlots(), isEmpty);
    });
  });

  // ──────────────────────────────────────────────────────────────────────
  // Custom maxManualSlots
  // ──────────────────────────────────────────────────────────────────────

  group('CustomMaxManualSlots', () {
    test('custom maxManualSlots limits slots', () async {
      final saveMgr = SaveMgr(maxManualSlots: 2);
      saveMgr.initialize();

      await saveMgr.manualSave(
        1,
        PlayerState(
          hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
        ),
        1,
      );

      expect(await saveMgr.hasSave(1), isTrue);
      expect(await saveMgr.hasSave(2), isFalse);
      expect(await saveMgr.hasSave(3), isFalse);
      expect(() => saveMgr.manualSave(3, PlayerState(
        hp: 100, maxHp: 100, atk: 5, def: 5, gold: 50, exp: 100, level: 1,
      ), 1), throwsArgumentError);
    });
  });
}
