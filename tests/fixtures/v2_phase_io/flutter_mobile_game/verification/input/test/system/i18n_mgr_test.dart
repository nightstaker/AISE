// I18n Manager Tests — 语言切换

import 'package:magic_tower/system/i18n_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('I18nMgr language switch', () {
    test('switch language updates translations', () {
      final i18n = I18nMgr();
      i18n.initialize();

      i18n.setLanguage('en');

      expect(i18n.currentLanguage, 'en');
      expect(i18n.translate('start_game'), 'Start Game');
      expect(i18n.translate('settings'), 'Settings');
    });

    test('chinese translations', () {
      final i18n = I18nMgr();
      i18n.initialize();

      i18n.setLanguage('zh');

      expect(i18n.currentLanguage, 'zh');
      expect(i18n.translate('start_game'), '开始游戏');
      expect(i18n.translate('settings'), '设置');
    });

    test('unknown key returns key itself', () {
      final i18n = I18nMgr();
      i18n.initialize();

      i18n.setLanguage('en');

      expect(i18n.translate('nonexistent_key'), 'nonexistent_key');
    });
  });
}
