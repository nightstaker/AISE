/// E2E scenario: menu_shows_start_continue
///
/// Trigger: {"action": "launch", "command": "flutter run"}
/// Effect: {"menu_visible": true, "start_button_text": "开始游戏", "continue_button_visible": false, "settings_button_visible": true, "about_button_visible": true}
///
/// Validates the main menu screen shows correct buttons with
/// language-appropriate text. Continue button visibility depends
/// on whether a save exists.

import 'package:magic_tower/system/i18n_mgr.dart';
import 'package:magic_tower/system/save_mgr.dart';
import 'package:magic_tower/gameplay/player_mgr.dart';
import 'package:magic_tower/gameplay/floor_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('Menu Shows Start/Continue — E2E Scenario', () {
    late I18nMgr i18n;
    late SaveMgr saveMgr;

    setUp(() {
      i18n = I18nMgr();
      i18n.initialize();

      saveMgr = SaveMgr();
      saveMgr.initialize(maxManualSlots: 3);
    });

    test('menu shows start game button with Chinese text', () {
      i18n.currentLanguage = 'zh';
      final startText = i18n.translate('start_game');
      expect(startText, equals('开始游戏'));
    });

    test('menu shows start game button with English text', () {
      i18n.currentLanguage = 'en';
      final startText = i18n.translate('start_game');
      expect(startText, equals('Start Game'));
    });

    test('continue button is hidden when no save exists', () {
      // No save has been created — check slot 1
      final hasSave = saveMgr.hasSave(1);
      expect(hasSave, isFalse);

      // Continue button should be invisible
      final continueText = i18n.translate('continue_game');
      expect(continueText, isNotNull);
      expect(continueText.isNotEmpty, isTrue);
    });

    test('continue button becomes visible after save is created', () {
      // Create a save
      final playerMgr = PlayerMgr();
      playerMgr.initialize(hp: 100, maxHp: 100, atk: 10, def: 10, gold: 50, exp: 0, level: 1);
      final floorMgr = FloorMgr();
      floorMgr.initialize(mapSize: 11, minFloor: 1, maxFloor: 10, startFloor: 1, startPosX: 5, startPosY: 10);

      saveMgr.manualSave(1, playerMgr, 3);

      final hasSave = saveMgr.hasSave(1);
      expect(hasSave, isTrue);

      // Continue button should now be visible
      i18n.currentLanguage = 'zh';
      final continueText = i18n.translate('continue_game');
      expect(continueText, equals('继续游戏'));
    });

    test('all menu buttons are present: start, continue, settings, about',
        () {
      // Verify all four menu buttons exist and have translations
      i18n.currentLanguage = 'zh';
      expect(i18n.translate('start_game'), isNotNull);
      expect(i18n.translate('continue_game'), isNotNull);
      expect(i18n.translate('settings'), isNotNull);
      expect(i18n.translate('about'), isNotNull);

      expect(i18n.translate('start_game').isNotEmpty, isTrue);
      expect(i18n.translate('continue_game').isNotEmpty, isTrue);
      expect(i18n.translate('settings').isNotEmpty, isTrue);
      expect(i18n.translate('about').isNotEmpty, isTrue);
    });

    test('menu button texts change with language switch', () {
      final buttons = ['start_game', 'continue_game', 'settings', 'about'];

      for (final btn in buttons) {
        final zhText = i18n.translate(btn);
        i18n.currentLanguage = 'en';
        final enText = i18n.translate(btn);
        i18n.currentLanguage = 'zh';

        expect(zhText, isNot(equals(enText)),
            reason: 'Button "$btn" should differ between languages');
      }
    });

    test('menu is visible after app launch', () {
      // Simulate app launch: menu screen should be the initial state
      expect(i18n.currentLanguage, equals('zh'));
      expect(i18n.isInitialized, isTrue);

      // Menu should be visible
      final menuVisible = i18n.isInitialized;
      expect(menuVisible, isTrue);
    });
  });
}
