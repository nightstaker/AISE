/// Settings screen — game configuration options.
///
/// Responsibilities:
/// - Toggle BGM volume.
/// - Toggle SFX volume.
/// - Switch display language (zh-CN / en-US).
/// - Clear save data.

import 'package:flutter/material.dart';

/// Settings screen widget.
class SettingsScreen extends StatefulWidget {
  /// Current BGM volume (0.0 to 1.0).
  final double bgmVolume;

  /// Current SFX volume (0.0 to 1.0).
  final double sfxVolume;

  /// Current language code.
  final String languageCode;

  /// Number of save slots available.
  final int saveSlotCount;

  /// Callback when BGM volume changes.
  final ValueChanged<double> onBgmVolumeChanged;

  /// Callback when SFX volume changes.
  final ValueChanged<double> onSfxVolumeChanged;

  /// Callback when language is changed.
  final ValueChanged<String> onLanguageChanged;

  /// Callback to clear all save data.
  final VoidCallback onClearSave;

  /// Callback to go back.
  final VoidCallback onBack;

  const SettingsScreen({
    super.key,
    this.bgmVolume = 0.8,
    this.sfxVolume = 1.0,
    this.languageCode = 'zh',
    this.saveSlotCount = 3,
    this.onBgmVolumeChanged = _noopDouble,
    this.onSfxVolumeChanged = _noopDouble,
    this.onLanguageChanged = _noopStr,
    this.onClearSave = _noop,
    this.onBack = _noop,
  });

  static void _noop() {}
  static void _noopDouble(double d) {}
  static void _noopStr(String s) {}

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();

  /// Initialize this screen. Called by the app's lifecycle init.
  void initialize() {
    // SettingsScreen is stateful; initialization handled in initState.
  }

  bool get isInitialized => true;
}

class _SettingsScreenState extends State<SettingsScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('设置'),
        backgroundColor: Colors.grey[800],
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: widget.onBack,
        ),
      ),
      backgroundColor: Colors.grey[900],
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // BGM Volume
          _buildSliderSetting(
            context,
            title: '背景音乐音量',
            subtitle: 'BGM Volume',
            value: widget.bgmVolume,
            onChanged: widget.onBgmVolumeChanged,
          ),
          const Divider(color: Colors.white24),
          // SFX Volume
          _buildSliderSetting(
            context,
            title: '音效音量',
            subtitle: 'SFX Volume',
            value: widget.sfxVolume,
            onChanged: widget.onSfxVolumeChanged,
          ),
          const Divider(color: Colors.white24),
          // Language
          _buildLanguageSetting(context),
          const Divider(color: Colors.white24),
          // Save slots
          _buildSaveSlotSetting(context),
          const Divider(color: Colors.white24),
          // Clear saves
          ListTile(
            title: const Text('清除存档'),
            subtitle: const Text('Clear Save Data'),
            trailing: ElevatedButton(
              onPressed: () => _showClearConfirm(context),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red[700],
              ),
              child: const Text('清除'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSliderSetting(
    BuildContext context, {
    required String title,
    required String subtitle,
    required double value,
    required ValueChanged<double> onChanged,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: const TextStyle(color: Colors.white, fontSize: 16)),
        Text(
          subtitle,
          style: TextStyle(color: Colors.white70, fontSize: 12),
        ),
        Slider(
          value: value,
          onChanged: onChanged,
          activeColor: Colors.amber,
        ),
        Text(
          ' ${(value * 100).toInt()}%',
          style: const TextStyle(color: Colors.amber),
        ),
      ],
    );
  }

  Widget _buildLanguageSetting(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '语言',
          style: TextStyle(color: Colors.white, fontSize: 16),
        ),
        const SizedBox(height: 4),
        SegmentedButton<String>(
          segments: const <ButtonSegment<String>>[
            ButtonSegment<String>(
              value: 'zh-CN',
              label: Text('中文'),
            ),
            ButtonSegment<String>(
              value: 'en-US',
              label: Text('English'),
            ),
          ],
          selected: {widget.languageCode},
          onSelectionChanged: (Set<String> newSelection) {
            if (newSelection.isNotEmpty) {
              widget.onLanguageChanged(newSelection.first);
            }
          },
        ),
      ],
    );
  }

  Widget _buildSaveSlotSetting(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '存档槽位: ${widget.saveSlotCount}',
          style: const TextStyle(color: Colors.white, fontSize: 16),
        ),
        const Text(
          'Save Slots',
          style: TextStyle(color: Colors.white70, fontSize: 12),
        ),
      ],
    );
  }

  void _showClearConfirm(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('确认清除'),
        content: const Text('确定要清除所有存档吗？此操作不可撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('取消'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              widget.onClearSave();
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.red[700],
            ),
            child: const Text('确认'),
          ),
        ],
      ),
    );
  }
}
