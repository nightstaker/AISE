/// E2E scenario: i18n_language_switch
///
/// Trigger: {"action": "tap", "target": "language_switch_button"}
/// Effect: {"language_changed": "en", "ui_text_updated": true, "start_game_translation": "Start Game"}
///
/// Validates language switching between Chinese and English, and that
/// UI text updates correctly after switch.

import 'package:magic_tower/system/i18n_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('i18n Language Switch — E2E Scenario', () {
    late I18nMgr i18n;

    setUp(() {
      i18n = I18nMgr();
      i18n.initialize();
    });

    test('default language is Chinese', () {
      expect(i18n.currentLanguage, equals('zh'));
    });

    test('switch from zh to en: start_game becomes "Start Game"', () {
      expect(i18n.currentLanguage, equals('zh'));

      i18n.currentLanguage = 'en';
      expect(i18n.currentLanguage, equals('en'));

      final translated = i18n.translate('start_game');
      expect(translated, equals('Start Game'));
    });

    test('switch from en back to zh: start_game becomes "开始游戏"', () {
      i18n.currentLanguage = 'en';
      i18n.currentLanguage = 'zh';
      expect(i18n.currentLanguage, equals('zh'));

      final translated = i18n.translate('start_game');
      expect(translated, equals('开始游戏'));
    });

    test('all menu keys translate correctly in both languages', () {
      // Chinese
      i18n.currentLanguage = 'zh';
      expect(i18n.translate('start_game'), equals('开始游戏'));
      expect(i18n.translate('continue_game'), equals('继续游戏'));
      expect(i18n.translate('settings'), equals('设置'));
      expect(i18n.translate('about'), equals('关于'));
      expect(i18n.translate('exit_game'), equals('退出游戏'));

      // English
      i18n.currentLanguage = 'en';
      expect(i18n.translate('start_game'), equals('Start Game'));
      expect(i18n.translate('continue_game'), equals('Continue'));
      expect(i18n.translate('settings'), equals('Settings'));
      expect(i18n.translate('about'), equals('About'));
      expect(i18n.translate('exit_game'), equals('Exit'));
    });

    test('HUD stat labels translate correctly', () {
      i18n.currentLanguage = 'zh';
      expect(i18n.translate('hp'), equals('生命'));
      expect(i18n.translate('atk'), equals('攻击'));
      expect(i18n.translate('def'), equals('防御'));
      expect(i18n.translate('gold'), equals('金币'));
      expect(i18n.translate('exp'), equals('经验'));
      expect(i18n.translate('level'), equals('等级'));
      expect(i18n.translate('floor'), equals('楼层'));

      i18n.currentLanguage = 'en';
      expect(i18n.translate('hp'), equals('HP'));
      expect(i18n.translate('atk'), equals('ATK'));
      expect(i18n.translate('def'), equals('DEF'));
      expect(i18n.translate('gold'), equals('Gold'));
      expect(i18n.translate('exp'), equals('EXP'));
      expect(i18n.translate('level'), equals('Lv'));
      expect(i18n.translate('floor'), equals('Floor'));
    });

    test('item names translate correctly', () {
      i18n.currentLanguage = 'zh';
      expect(i18n.translate('key_yellow'), equals('黄钥匙'));
      expect(i18n.translate('key_blue'), equals('蓝钥匙'));
      expect(i18n.translate('key_red'), equals('红钥匙'));
      expect(i18n.translate('potion_red'), equals('红血瓶'));
      expect(i18n.translate('potion_blue'), equals('蓝血瓶'));
      expect(i18n.translate('gem_red'), equals('红宝石'));
      expect(i18n.translate('gem_blue'), equals('蓝宝石'));

      i18n.currentLanguage = 'en';
      expect(i18n.translate('key_yellow'), equals('Yellow Key'));
      expect(i18n.translate('key_blue'), equals('Blue Key'));
      expect(i18n.translate('key_red'), equals('Red Key'));
      expect(i18n.translate('potion_red'), equals('Red Potion'));
      expect(i18n.translate('potion_blue'), equals('Blue Potion'));
      expect(i18n.translate('gem_red'), equals('Ruby'));
      expect(i18n.translate('gem_blue'), equals('Sapphire'));
    });

    test('battle and shop translations', () {
      i18n.currentLanguage = 'zh';
      expect(i18n.translate('victory'), equals('胜利'));
      expect(i18n.translate('defeat'), equals('失败'));
      expect(i18n.translate('buy'), equals('购买'));
      expect(i18n.translate('not_enough_gold'), equals('金币不足'));
      expect(i18n.translate('shop'), equals('商店'));

      i18n.currentLanguage = 'en';
      expect(i18n.translate('victory'), equals('Victory'));
      expect(i18n.translate('defeat'), equals('Defeat'));
      expect(i18n.translate('buy'), equals('Buy'));
      expect(i18n.translate('not_enough_gold'), equals('Not enough gold'));
      expect(i18n.translate('shop'), equals('Shop'));
    });

    test('unknown key returns key itself', () {
      i18n.currentLanguage = 'zh';
      expect(i18n.translate('unknown_key'), equals('unknown_key'));

      i18n.currentLanguage = 'en';
      expect(i18n.translate('unknown_key'), equals('unknown_key'));
    });

    test('language switch updates UI text end-to-end', () {
      // Simulate a full UI text update cycle
      i18n.currentLanguage = 'zh';
      final zhMenu = i18n.translate('start_game');

      i18n.currentLanguage = 'en';
      final enMenu = i18n.translate('start_game');

      expect(zhMenu, isNot(equals(enMenu)));
      expect(zhMenu, equals('开始游戏'));
      expect(enMenu, equals('Start Game'));
    });
  });
}
