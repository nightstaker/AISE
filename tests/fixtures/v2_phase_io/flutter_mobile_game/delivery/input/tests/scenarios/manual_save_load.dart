/// E2E scenario: manual_save_load
///
/// Trigger: {"action": "menu", "target": "manual_save"}
/// Effect: {"save_slot_1_populated": true, "loaded_state_matches": true}
///
/// Validates manual save to slot 1, then load restores full game state.
/// Supports at least 3 save slots.

import 'package:magic_tower/gameplay/floor_mgr.dart';
import 'package:magic_tower/gameplay/player_mgr.dart';
import 'package:magic_tower/system/save_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('Manual Save & Load — E2E Scenario', () {
    late SaveMgr saveMgr;
    late PlayerMgr playerMgr;
    late FloorMgr floorMgr;

    setUp(() {
      saveMgr = SaveMgr(maxManualSlots: 3);
      saveMgr.initialize();

      playerMgr = PlayerMgr();
      playerMgr.initialize(
        hp: 100, maxHp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1,
      );

      floorMgr = FloorMgr();
      floorMgr.initialize(
        mapSize: 11, minFloor: 1, maxFloor: 10,
        startFloor: 1, startPosX: 5, startPosY: 10,
      );
    });

    test('save slot 1 is populated after manual save', () async {
      final state = PlayerState(
        hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1,
      );
      await saveMgr.manualSave(1, state, 1);

      final hasSave = await saveMgr.hasSave(1);
      expect(hasSave, isTrue);
    });

    test('loaded state matches saved state', () async {
      final state = PlayerState(
        hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1,
      );
      await saveMgr.manualSave(1, state, 1);

      final loaded = await saveMgr.loadSave(1);
      expect(loaded, isNotNull);
      expect(loaded!.currentFloor, equals(1));
      expect(loaded.playerState.hp, equals(100));
      expect(loaded.playerState.atk, equals(10));
      expect(loaded.playerState.def, equals(10));
      expect(loaded.playerState.gold, equals(50));
      expect(loaded.playerState.level, equals(1));
    });

    test('supports at least 3 save slots', () async {
      // Save to all 3 slots
      for (var slot = 1; slot <= 3; slot++) {
        final state = PlayerState(
          hp: 100, atk: 10, def: 10, gold: slot * 50, exp: 0, level: slot,
        );
        await saveMgr.manualSave(slot, state, slot);
      }

      // Verify all slots
      for (var slot = 1; slot <= 3; slot++) {
        final hasSave = await saveMgr.hasSave(slot);
        expect(hasSave, isTrue, reason: 'Slot $slot should be occupied');

        final loaded = await saveMgr.loadSave(slot);
        expect(loaded, isNotNull);
        expect(loaded!.playerState.gold, equals(slot * 50));
        expect(loaded.playerState.level, equals(slot));
      }
    });

    test('save and load different states to different slots', () async {
      // Slot 1: floor 1, HP 100
      await saveMgr.manualSave(1,
        PlayerState(hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1),
        1);

      // Slot 2: floor 3, HP 200
      await saveMgr.manualSave(2,
        PlayerState(hp: 200, atk: 15, def: 12, gold: 100, exp: 50, level: 2),
        3);

      final s1 = await saveMgr.loadSave(1);
      expect(s1!.currentFloor, equals(1));
      expect(s1.playerState.hp, equals(100));

      final s2 = await saveMgr.loadSave(2);
      expect(s2!.currentFloor, equals(3));
      expect(s2.playerState.hp, equals(200));
    });

    test('empty slot returns null on load', () async {
      final loaded = await saveMgr.loadSave(3);
      expect(loaded, isNull);
    });

    test('out-of-range slot returns null', () async {
      final loaded = await saveMgr.loadSave(0);
      expect(loaded, isNull);

      final loaded2 = await saveMgr.loadSave(4);
      expect(loaded2, isNull);
    });

    test('overwrite existing save slot', () async {
      await saveMgr.manualSave(1,
        PlayerState(hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1),
        1);

      // Overwrite slot 1
      await saveMgr.manualSave(1,
        PlayerState(hp: 200, atk: 20, def: 15, gold: 100, exp: 100, level: 3),
        5);

      final loaded = await saveMgr.loadSave(1);
      expect(loaded!.playerState.hp, equals(200));
      expect(loaded.playerState.gold, equals(100));
      expect(loaded.currentFloor, equals(5));
    });

    test('invalid slot throws ArgumentError', () async {
      expect(
        () => saveMgr.manualSave(0,
          PlayerState(hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1),
          1),
      throwsArgumentError);

      expect(
        () => saveMgr.manualSave(4,
          PlayerState(hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1),
          1),
      throwsArgumentError);
    });

    test('delete save slot frees it for reuse', () async {
      await saveMgr.manualSave(1,
        PlayerState(hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1),
        1);

      expect(await saveMgr.hasSave(1), isTrue);

      await saveMgr.deleteSave(1);
      expect(await saveMgr.hasSave(1), isFalse);

      final loaded = await saveMgr.loadSave(1);
      expect(loaded, isNull);
    });

    test('save includes timestamp', () async {
      await saveMgr.manualSave(1,
        PlayerState(hp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1),
        1);

      final loaded = await saveMgr.loadSave(1);
      expect(loaded!.timestamp.isNotEmpty, isTrue);
      expect(() => DateTime.parse(loaded.timestamp), returnsNormally);
    });
  });
}
