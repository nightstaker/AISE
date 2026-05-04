// Settings Manager Tests — 设置管理

import 'package:magic_tower/system/settings_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('SettingsMgr', () {
    // ── Default values ────────────────────────────────────────────────

    test('default settings after construction', () {
      final settings = SettingsMgr();
      settings.initialize();

      expect(settings.currentLanguage, 'zh');
      expect(settings.bgMVolume, 0.8);
      expect(settings.sfxVolume, 1.0);
    });

    test('isInitialized is false before initialize()', () {
      final settings = SettingsMgr();
      expect(settings.isInitialized, isFalse);
    });

    test('isInitialized is true after initialize()', () {
      final settings = SettingsMgr();
      settings.initialize();
      expect(settings.isInitialized, isTrue);
    });

    // ── Language ──────────────────────────────────────────────────────

    test('setLanguage changes currentLanguage', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setLanguage('en');
      expect(settings.currentLanguage, 'en');
    });

    test('setLanguage supports multiple locale codes', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setLanguage('ja');
      expect(settings.currentLanguage, 'ja');

      settings.setLanguage('ko');
      expect(settings.currentLanguage, 'ko');

      settings.setLanguage('zh-CN');
      expect(settings.currentLanguage, 'zh-CN');
    });

    test('setLanguage throws StateError before initialize', () {
      final settings = SettingsMgr();
      expect(() => settings.setLanguage('en'), throwsStateError);
    });

    // ── BGM Volume ────────────────────────────────────────────────────

    test('setBgmVolume clamps to 0.0', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setBgmVolume(-1.0);
      expect(settings.bgMVolume, 0.0);
    });

    test('setBgmVolume clamps to 1.0', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setBgmVolume(2.0);
      expect(settings.bgMVolume, 1.0);
    });

    test('setBgmVolume accepts mid-range values', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setBgmVolume(0.5);
      expect(settings.bgMVolume, 0.5);
    });

    test('setBgmVolume throws StateError before initialize', () {
      final settings = SettingsMgr();
      expect(() => settings.setBgmVolume(0.5), throwsStateError);
    });

    // ── SFX Volume ────────────────────────────────────────────────────

    test('setSfxVolume clamps to 0.0', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setSfxVolume(-0.5);
      expect(settings.sfxVolume, 0.0);
    });

    test('setSfxVolume clamps to 1.0', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setSfxVolume(3.0);
      expect(settings.sfxVolume, 1.0);
    });

    test('setSfxVolume accepts mid-range values', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setSfxVolume(0.3);
      expect(settings.sfxVolume, 0.3);
    });

    test('setSfxVolume throws StateError before initialize', () {
      final settings = SettingsMgr();
      expect(() => settings.setSfxVolume(0.5), throwsStateError);
    });

    // ── Reset ─────────────────────────────────────────────────────────

    test('reset restores all defaults', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.setLanguage('en');
      settings.setBgmVolume(0.3);
      settings.setSfxVolume(0.7);

      settings.reset();

      expect(settings.currentLanguage, 'zh');
      expect(settings.bgMVolume, 0.8);
      expect(settings.sfxVolume, 1.0);
    });

    test('reset works without initialize', () {
      final settings = SettingsMgr();
      // reset() is allowed even before initialize (it just resets fields)
      settings.reset();
      expect(settings.currentLanguage, 'zh');
      expect(settings.bgMVolume, 0.8);
      expect(settings.sfxVolume, 1.0);
    });

    // ── toJson / fromJson round-trip ─────────────────────────────────

    test('toJson produces correct structure', () {
      final settings = SettingsMgr();
      settings.initialize();
      settings.setLanguage('en');
      settings.setBgmVolume(0.5);
      settings.setSfxVolume(0.3);

      final json = settings.toJson();

      expect(json['language'], 'en');
      expect(json['bgmVolume'], 0.5);
      expect(json['sfxVolume'], 0.3);
    });

    test('fromJson restores settings', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.fromJson({
        'language': 'en',
        'bgmVolume': 0.6,
        'sfxVolume': 0.4,
      });

      expect(settings.currentLanguage, 'en');
      expect(settings.bgMVolume, 0.6);
      expect(settings.sfxVolume, 0.4);
    });

    test('toJson round-trip preserves values', () {
      final settings = SettingsMgr();
      settings.initialize();
      settings.setLanguage('ja');
      settings.setBgmVolume(0.75);
      settings.setSfxVolume(0.25);

      final json = settings.toJson();

      final restored = SettingsMgr();
      restored.initialize();
      restored.fromJson(json);

      expect(restored.currentLanguage, 'ja');
      expect(restored.bgMVolume, 0.75);
      expect(restored.sfxVolume, 0.25);
    });

    test('fromJson ignores missing keys gracefully', () {
      final settings = SettingsMgr();
      settings.initialize();

      settings.fromJson({});

      // Should keep defaults when keys are missing
      expect(settings.currentLanguage, 'zh');
      expect(settings.bgMVolume, 0.8);
      expect(settings.sfxVolume, 1.0);
    });

    // ── Serialization helpers ─────────────────────────────────────────

    test('toJson with default values', () {
      final settings = SettingsMgr();
      settings.initialize();

      final json = settings.toJson();

      expect(json['language'], 'zh');
      expect(json['bgmVolume'], 0.8);
      expect(json['sfxVolume'], 1.0);
    });

    // ── Multiple instances ───────────────────────────────────────────

    test('two SettingsMgr instances are independent', () {
      final s1 = SettingsMgr();
      s1.initialize();
      s1.setLanguage('en');

      final s2 = SettingsMgr();
      s2.initialize();
      // s2 should still have default

      expect(s2.currentLanguage, 'zh');
    });

    test('two SettingsMgr instances can have different settings', () {
      final s1 = SettingsMgr();
      s1.initialize();
      s1.setBgmVolume(0.5);

      final s2 = SettingsMgr();
      s2.initialize();
      s2.setBgmVolume(0.9);

      expect(s1.bgMVolume, 0.5);
      expect(s2.bgMVolume, 0.9);
    });
  });
}
