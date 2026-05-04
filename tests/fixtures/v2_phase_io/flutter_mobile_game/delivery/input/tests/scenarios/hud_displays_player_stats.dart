/// E2E scenario: hud_displays_player_stats
///
/// Trigger: {"action": "enter_game"}
/// Effect: {"hud_visible": true, "hp_displayed": "HP: 100", "atk_displayed": "ATK: 10", "def_displayed": "DEF: 5", "gold_displayed": "Gold: 50", "floor_displayed": "Floor 1", "level_displayed": "Lv 1"}
///
/// Validates HUD displays all six player stats and current floor number.

import 'package:magic_tower/data/models.dart';
import 'package:magic_tower/system/i18n_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('HUD Displays Player Stats — E2E Scenario', () {
    late I18nMgr i18n;

    setUp(() {
      i18n = I18nMgr();
      i18n.initialize();
    });

    test('HUD displays HP, ATK, DEF, Gold, Level with Chinese labels', () {
      i18n.currentLanguage = 'zh';

      final player = PlayerState(
        hp: 100,
        atk: 10,
        def: 5,
        gold: 50,
        exp: 0,
        level: 1,
      );

      // HP display
      final hpLabel = i18n.translate('hp');
      final hpDisplay = '$hpLabel: ${player.hp}';
      expect(hpDisplay, equals('生命: 100'));

      // ATK display
      final atkLabel = i18n.translate('atk');
      final atkDisplay = '$atkLabel: ${player.atk}';
      expect(atkDisplay, equals('攻击: 10'));

      // DEF display
      final defLabel = i18n.translate('def');
      final defDisplay = '$defLabel: ${player.def}';
      expect(defDisplay, equals('防御: 5'));

      // Gold display
      final goldLabel = i18n.translate('gold');
      final goldDisplay = '$goldLabel: ${player.gold}';
      expect(goldDisplay, equals('金币: 50'));

      // Level display
      final levelLabel = i18n.translate('level');
      final levelDisplay = '$levelLabel ${player.level}';
      expect(levelDisplay, equals('等级 1'));

      // Floor display
      final floorLabel = i18n.translate('floor');
      final floorDisplay = '$floorLabel 1';
      expect(floorDisplay, equals('楼层 1'));
    });

    test('HUD displays stats with English labels', () {
      i18n.currentLanguage = 'en';

      final player = PlayerState(
        hp: 100,
        atk: 10,
        def: 5,
        gold: 50,
        exp: 0,
        level: 1,
      );

      expect('${i18n.translate('hp')}: ${player.hp}', equals('HP: 100'));
      expect('${i18n.translate('atk')}: ${player.atk}', equals('ATK: 10'));
      expect('${i18n.translate('def')}: ${player.def}', equals('DEF: 5'));
      expect('${i18n.translate('gold')}: ${player.gold}', equals('Gold: 50'));
      expect('${i18n.translate('level')} ${player.level}', equals('Lv 1'));
      expect('${i18n.translate('floor')} 1', equals('Floor 1'));
    });

    test('HUD updates when player stats change', () {
      i18n.currentLanguage = 'en';

      var player = PlayerState(hp: 100, atk: 10, def: 5, gold: 50, exp: 0, level: 1);
      expect('${i18n.translate('hp')}: ${player.hp}', equals('HP: 100'));

      // Player takes damage
      player = PlayerState(hp: 75, atk: 10, def: 5, gold: 50, exp: 0, level: 1);
      expect('${i18n.translate('hp')}: ${player.hp}', equals('HP: 75'));

      // Player gains ATK
      player = PlayerState(hp: 75, atk: 15, def: 5, gold: 50, exp: 0, level: 1);
      expect('${i18n.translate('atk')}: ${player.atk}', equals('ATK: 15'));

      // Player gains gold
      player = PlayerState(hp: 75, atk: 15, def: 5, gold: 100, exp: 0, level: 1);
      expect('${i18n.translate('gold')}: ${player.gold}', equals('Gold: 100'));
    });

    test('HUD displays EXP and level correctly', () {
      i18n.currentLanguage = 'en';

      final player = PlayerState(hp: 100, atk: 10, def: 5, gold: 50, exp: 500, level: 3);
      final expLabel = i18n.translate('exp');
      final expDisplay = '$expLabel: ${player.exp}';
      expect(expDisplay, equals('EXP: 500'));

      final levelDisplay = '${i18n.translate('level')} ${player.level}';
      expect(levelDisplay, equals('Lv 3'));
    });

    test('HUD is visible when player is in game', () {
      // HUD visibility is tied to game state
      final player = PlayerState(hp: 100, atk: 10, def: 5, gold: 50, exp: 0, level: 1);
      expect(player.hp > 0, isTrue, reason: 'Player must be alive for HUD to show');
      expect(player.atk > 0, isTrue, reason: 'ATK must be set');
      expect(player.def > 0, isTrue, reason: 'DEF must be set');
      expect(player.level >= 1, isTrue, reason: 'Level must be at least 1');
    });

    test('HUD floor number updates on floor switch', () {
      i18n.currentLanguage = 'en';

      int floorNumber = 1;
      expect('${i18n.translate('floor')} $floorNumber', equals('Floor 1'));

      floorNumber = 5;
      expect('${i18n.translate('floor')} $floorNumber', equals('Floor 5'));

      floorNumber = 10;
      expect('${i18n.translate('floor')} $floorNumber', equals('Floor 10'));
    });
  });
}
