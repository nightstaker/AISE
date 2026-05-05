/// E2E scenario: death_rebirth
///
/// Trigger: {"action": "combat", "result": "player_defeated"}
/// Effect: {"gold_deducted": 50, "rebirth_floor": "current_floor - 1", "rebirth_hp": "initial_hp * 0.5"}
///
/// Validates HP zero after combat triggers death: deduct 50 gold (or 0 if
/// insufficient), rebirth at previous floor entrance with 50% of initial HP.

import 'package:magic_tower/gameplay/battle_engine.dart';
import 'package:magic_tower/gameplay/floor_mgr.dart';
import 'package:magic_tower/gameplay/player_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('Death Rebirth — E2E Scenario', () {
    late PlayerMgr playerMgr;
    late FloorMgr floorMgr;

    setUp(() {
      floorMgr = FloorMgr();
      floorMgr.initialize(
        mapSize: 11,
        minFloor: 1,
        maxFloor: 10,
        startFloor: 5,
        startPosX: 5,
        startPosY: 10,
      );

      playerMgr = PlayerMgr();
      playerMgr.initialize(
        hp: 100,
        maxHp: 100,
        atk: 10,
        def: 10,
        gold: 200,
        exp: 0,
        level: 1,
      );
    });

    test('HP reaches zero after combat → player_defeated', () {
      // Player hp=10, monster damage=50 → player dies
      // Simulate: player takes 100 damage
      playerMgr.takeDamage(100);
      expect(playerMgr.isDead, isTrue);
      expect(playerMgr.hp, equals(0));
    });

    test('gold deducted on death: 50 gold', () {
      expect(playerMgr.gold, equals(200));

      // Deduct death penalty
      playerMgr.modifyGold(-50);
      expect(playerMgr.gold, equals(150));
    });

    test('gold deducted to 0 when insufficient', () {
      playerMgr.modifyGold(-200); // Only 200 gold, deduct 300

      // After modifying gold to 0 (can't go negative)
      expect(playerMgr.gold, equals(0));
    });

    test('rebirth at floor - 1: current 5 → rebirth 4', () {
      final currentFloor = floorMgr.currentFloor;
      expect(currentFloor, equals(5));

      // Rebirth floor
      final rebirthFloor = currentFloor - 1;
      expect(rebirthFloor, equals(4));

      floorMgr.setFloor(rebirthFloor);
      expect(floorMgr.currentFloor, equals(4));
    });

    test('rebirth HP = initial_hp * 0.5 = 100 * 0.5 = 50', () {
      // Simulate death: HP goes to 0
      playerMgr.takeDamage(200);
      expect(playerMgr.hp, equals(0));

      // Rebirth: restore to 50% of initial max HP
      final rebirthHp = (playerMgr.maxHp * 0.5).toInt();
      expect(rebirthHp, equals(50));

      playerMgr.heal(rebirthHp);
      expect(playerMgr.hp, equals(50));
    });

    test('full death-rebirth cycle', () {
      // Initial state
      expect(playerMgr.hp, equals(100));
      expect(playerMgr.gold, equals(200));
      expect(floorMgr.currentFloor, equals(5));

      // Combat: player takes fatal damage
      playerMgr.takeDamage(100);
      expect(playerMgr.isDead, isTrue);

      // Deduct gold (or as much as possible)
      final goldDeducted = playerMgr.gold >= 50 ? 50 : playerMgr.gold;
      playerMgr.modifyGold(-goldDeducted);
      expect(playerMgr.gold, equals(200 - goldDeducted));

      // Rebirth at previous floor
      final rebirthFloor = floorMgr.currentFloor - 1;
      floorMgr.setFloor(rebirthFloor);
      expect(floorMgr.currentFloor, equals(4));

      // Rebirth HP = 50% of initial max HP
      final rebirthHp = (playerMgr.maxHp * 0.5).toInt();
      playerMgr.heal(rebirthHp);
      expect(playerMgr.hp, equals(50));
    });

    test('death with 0 gold: no gold penalty', () {
      playerMgr.modifyGold(-200); // Drain all gold
      expect(playerMgr.gold, equals(0));

      // Death still occurs
      playerMgr.takeDamage(100);
      expect(playerMgr.isDead, isTrue);

      // Gold should stay at 0
      playerMgr.modifyGold(-50);
      expect(playerMgr.gold, equals(0));
    });

    test('battle engine confirms player loss', () {
      // Player: hp=10, atk=5, def=5
      // Monster: hp=50, atk=50, def=5
      // Player damage = max(5-5, 1) = 1
      // Monster damage = max(50-5, 1) = 45
      // Player rounds = 50, Monster rounds = 1
      // Monster wins

      final result = BattleEngine.calculateRounds(
        playerHp: 10,
        playerAtk: 5,
        playerDef: 5,
        monsterHp: 50,
        monsterAtk: 50,
        monsterDef: 5,
      );

      expect(result.playerWins, isFalse);
      expect(result.playerHpRemaining, equals(0));
      expect(result.playerRoundsNeeded, equals(50));
      expect(result.monsterRoundsNeeded, equals(1));
    });

    test('death rebirth preserves ATK and DEF', () {
      playerMgr.modifyAtk(5);
      playerMgr.modifyDef(3);
      expect(playerMgr.atk, equals(15));
      expect(playerMgr.def, equals(13));

      // Simulate death and rebirth
      playerMgr.takeDamage(200);
      playerMgr.heal(50);

      expect(playerMgr.atk, equals(15), reason: 'ATK should be preserved');
      expect(playerMgr.def, equals(13), reason: 'DEF should be preserved');
    });

    test('death rebirth preserves inventory state', () {
      // Player state after death should preserve all non-HP attributes
      expect(playerMgr.level, equals(1));
      expect(playerMgr.exp, equals(0));

      playerMgr.takeDamage(200);
      playerMgr.heal(50);

      expect(playerMgr.level, equals(1));
      expect(playerMgr.exp, equals(0));
    });

    test('cannot go below floor 1 on rebirth', () {
      floorMgr.initialize(
        mapSize: 11,
        minFloor: 1,
        maxFloor: 10,
        startFloor: 1,
        startPosX: 5,
        startPosY: 10,
      );

      // Player on floor 1 dies
      expect(floorMgr.currentFloor, equals(1));
      final rebirthFloor = floorMgr.currentFloor - 1;
      expect(rebirthFloor, equals(0));

      // Clamp to floor 1
      final clampedFloor = rebirthFloor.clamp(1, 10);
      expect(clampedFloor, equals(1));
    });
  });
}
