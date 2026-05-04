// ignore_for_file: public_member_api_docs

import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// 设置管理器 — 设置持久化 + 配置管理
class SettingsMgr {
  SettingsMgr();

  bool _initialized = false;

  /// Whether [initialize] has been called.
  bool get isInitialized => _initialized;

  String currentLanguage = 'zh';
  double bgMVolume = 0.8;
  double sfxVolume = 1.0;

  String? _savePath;

  void initialize() {
    _initialized = true;
  }

  // ------------------------------------------------------------------
  // Internal helpers
  // ------------------------------------------------------------------

  Future<String> _getSavePath() async {
    if (_savePath != null) return _savePath!;
    final dir = await getApplicationDocumentsDirectory();
    _savePath = '${dir.path}/settings.json';
    return _savePath!;
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  void setLanguage(String language) {
    if (!_initialized) {
      throw StateError('SettingsMgr not initialized');
    }
    currentLanguage = language;
  }

  /// Set BGM volume.  Clamped to [0.0, 1.0].
  void setBgmVolume(double volume) {
    if (!_initialized) {
      throw StateError('SettingsMgr not initialized');
    }
    bgMVolume = volume.clamp(0.0, 1.0);
  }

  /// Set SFX volume.  Clamped to [0.0, 1.0].
  void setSfxVolume(double volume) {
    if (!_initialized) {
      throw StateError('SettingsMgr not initialized');
    }
    sfxVolume = volume.clamp(0.0, 1.0);
  }

  /// Persist settings to disk.
  Future<void> save() async {
    if (!_initialized) {
      throw StateError('SettingsMgr not initialized');
    }
    final file = File(await _getSavePath());
    await file.writeAsString(
      jsonEncode({
        'language': currentLanguage,
        'bgmVolume': bgMVolume,
        'sfxVolume': sfxVolume,
      }),
    );
  }

  /// Load persisted settings from disk.  Returns `false` when no
  /// previous save exists (in which case defaults remain).
  Future<bool> load() async {
    if (!_initialized) {
      throw StateError('SettingsMgr not initialized');
    }
    final file = File(await _getSavePath());
    if (!await file.exists()) return false;
    try {
      final raw = await file.readAsAsString();
      final json = jsonDecode(raw) as Map<String, dynamic>;
      if (json['language'] is String) currentLanguage = json['language'];
      if (json['bgmVolume'] is num) bgMVolume = json['bgmVolume'].toDouble();
      if (json['sfxVolume'] is num) sfxVolume = json['sfxVolume'].toDouble();
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Reset all settings to factory defaults.
  void reset() {
    currentLanguage = 'zh';
    bgMVolume = 0.8;
    sfxVolume = 1.0;
  }

  // ------------------------------------------------------------------
  // JSON serialisation
  // ------------------------------------------------------------------

  /// Serialise current settings to a JSON-compatible map.
  Map<String, dynamic> toJson() {
    return {
      'language': currentLanguage,
      'bgmVolume': bgMVolume,
      'sfxVolume': sfxVolume,
    };
  }

  /// Restore settings from a JSON-compatible map.
  void fromJson(Map<String, dynamic> json) {
    if (json['language'] is String) currentLanguage = json['language'];
    if (json['bgmVolume'] is num) bgMVolume = (json['bgmVolume'] as num).toDouble();
    if (json['sfxVolume'] is num) sfxVolume = (json['sfxVolume'] as num).toDouble();
  }
}
