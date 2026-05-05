/// Tests for SettingsScreen — game configuration options.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:magic_tower/ui/settings_screen.dart';

void main() {
  group('SettingsScreen', () {
    /// Build the settings screen in a testable tree.
    Widget _buildWidget({
      double bgmVolume = 0.7,
      double sfxVolume = 0.5,
      String languageCode = 'zh-CN',
      int saveSlotCount = 3,
      required ValueChanged<double> onBgmVolumeChanged,
      required ValueChanged<double> onSfxVolumeChanged,
      required ValueChanged<String> onLanguageChanged,
      required VoidCallback onClearSave,
      required VoidCallback onBack,
    }) {
      return MaterialApp(
        home: Scaffold(
          body: SettingsScreen(
            bgmVolume: bgmVolume,
            sfxVolume: sfxVolume,
            languageCode: languageCode,
            saveSlotCount: saveSlotCount,
            onBgmVolumeChanged: onBgmVolumeChanged,
            onSfxVolumeChanged: onSfxVolumeChanged,
            onLanguageChanged: onLanguageChanged,
            onClearSave: onClearSave,
            onBack: onBack,
          ),
        ),
      );
    }

    testWidgets('displays BGM volume slider', (tester) async {
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () {},
        onBack: () {},
      ));

      expect(find.text('背景音乐音量'), findsOneWidget);
      expect(find.byType(Slider), findsNWidgets(2));
    });

    testWidgets('displays SFX volume slider', (tester) async {
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () {},
        onBack: () {},
      ));

      expect(find.text('音效音量'), findsOneWidget);
    });

    testWidgets('displays language selector', (tester) async {
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () {},
        onBack: () {},
      ));

      expect(find.text('语言'), findsOneWidget);
      expect(find.text('中文'), findsOneWidget);
      expect(find.text('English'), findsOneWidget);
    });

    testWidgets('language change callback fires', (tester) async {
      String? newLang;
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (lang) => newLang = lang,
        onClearSave: () {},
        onBack: () {},
      ));

      // Tap the English segment.
      await tester.tap(find.text('English'));
      expect(newLang, equals('en-US'));
    });

    testWidgets('displays save slot count', (tester) async {
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () {},
        onBack: () {},
      ));

      expect(find.textContaining('3'), findsOneWidget);
    });

    testWidgets('clear save button triggers confirmation', (tester) async {
      var clearCalled = false;
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () => clearCalled = true,
        onBack: () {},
      ));

      await tester.tap(find.text('清除'));
      await tester.pumpAndSettle();

      // Confirm dialog should appear.
      expect(find.text('确认'), findsOneWidget);
      await tester.tap(find.text('确认'));
      await tester.pumpAndSettle();

      expect(clearCalled, isTrue);
    });

    testWidgets('back button callback fires', (tester) async {
      var backCalled = false;
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () {},
        onBack: () => backCalled = true,
      ));

      await tester.tap(find.byIcon(Icons.arrow_back));
      expect(backCalled, isTrue);
    });

    testWidgets('shows volume percentage', (tester) async {
      await tester.pumpWidget(_buildWidget(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () {},
        onBack: () {},
      ));

      expect(find.textContaining('70%'), findsOneWidget);
      expect(find.textContaining('50%'), findsOneWidget);
    });

    test('initialize and isInitialized work', () {
      final screen = SettingsScreen(
        bgmVolume: 0.7,
        sfxVolume: 0.5,
        languageCode: 'zh-CN',
        saveSlotCount: 3,
        onBgmVolumeChanged: (_) {},
        onSfxVolumeChanged: (_) {},
        onLanguageChanged: (_) {},
        onClearSave: () {},
        onBack: () {},
      );
      screen.initialize();
      expect(screen.isInitialized, isTrue);
    });
  });
}
