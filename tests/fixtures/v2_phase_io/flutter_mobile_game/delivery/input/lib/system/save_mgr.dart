/// Save Manager — 自动存档 / 手动存档 JSON 文件读写
///
/// Provides auto-save (single file, overwritten each time) and
/// manual save (up to [maxManualSlots] numbered slots, 1-based).
/// All persistence uses JSON-encoded files on the device's document
/// directory via [path_provider].

import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../data/models.dart';

/// Default number of manual save slots.
const int kDefaultManualSlots = 3;

// ──────────────────────────────────────────────────────────────────────
// SaveState — serialisable snapshot of the game state
// ──────────────────────────────────────────────────────────────────────

/// A persisted save snapshot (auto-save or manual slot).
class SaveState {
  SaveState({
    required this.currentFloor,
    required this.playerState,
    required this.timestamp,
    this.bossDefeated = const <String>{},
    this.npcTriggered = const <String>{},
    this.inventory = const <String>{},
  });

  /// Current floor number (1-based).
  final int currentFloor;

  /// Player state snapshot.
  final PlayerState playerState;

  /// ISO-8601 timestamp of when the save was written.
  final String timestamp;

  /// Set of boss IDs that have been defeated on this floor.
  final Set<String> bossDefeated;

  /// Set of NPC dialogue IDs that have been triggered.
  final Set<String> npcTriggered;

  /// Set of item IDs collected on this floor.
  final Set<String> inventory;

  // -- JSON serialisation ------------------------------------------------

  Map<String, dynamic> toJson() {
    return {
      'floor': currentFloor,
      'player': playerState.toJson(),
      'timestamp': timestamp,
      'bossDefeated': bossDefeated.toList(),
      'npcTriggered': npcTriggered.toList(),
      'inventory': inventory.toList(),
    };
  }

  factory SaveState.fromJson(Map<String, dynamic> json) {
    return SaveState(
      currentFloor: json['floor'] as int,
      playerState: PlayerState.fromJson(
        json['player'] as Map<String, dynamic>,
      ),
      timestamp: json['timestamp'] as String,
      bossDefeated: _toSet(json['bossDefeated']),
      npcTriggered: _toSet(json['npcTriggered']),
      inventory: _toSet(json['inventory']),
    );
  }

  // -- helpers -----------------------------------------------------------

  static Set<String> _toSet(dynamic v) {
    if (v == null) return const {};
    if (v is List) return v.map((e) => e.toString()).toSet();
    return {v.toString()};
  }

  // -- equality ----------------------------------------------------------

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is SaveState &&
          currentFloor == other.currentFloor &&
          playerState == other.playerState &&
          timestamp == other.timestamp &&
          bossDefeated == other.bossDefeated &&
          npcTriggered == other.npcTriggered &&
          inventory == other.inventory;

  @override
  int get hashCode =>
      currentFloor.hashCode ^
      playerState.hashCode ^
      timestamp.hashCode ^
      bossDefeated.hashCode ^
      npcTriggered.hashCode ^
      inventory.hashCode;
}

// ──────────────────────────────────────────────────────────────────────
// SaveMgr
// ──────────────────────────────────────────────────────────────────────

/// Manages auto-save and manual save slots for the game.
///
/// Auto-save is a single file that is overwritten on every call to
/// [autoSave].  Manual saves are stored in numbered slots
/// (1..[maxManualSlots]) and can be independently read / deleted.
class SaveMgr {
  SaveMgr({this.maxManualSlots = kDefaultManualSlots});

  bool _initialized = false;
  final int maxManualSlots;

  String? _autoSavePath;
  String? _manualSaveDir;

  // -- lifecycle -------------------------------------------------------

  bool get isInitialized => _initialized;

  /// Initialise the save manager.  Must be called before any
  /// save/load operation on Flutter.
  void initialize() {
    _initialized = true;
  }

  // -- private helpers -------------------------------------------------

  Future<String> _getAutoSavePath() async {
    if (_autoSavePath != null) return _autoSavePath!;
    final dir = await getApplicationDocumentsDirectory();
    _autoSavePath = '${dir.path}/autosave.json';
    return _autoSavePath!;
  }

  Future<String> _getManualSaveDir() async {
    if (_manualSaveDir != null) return _manualSaveDir!;
    final dir = await getApplicationDocumentsDirectory();
    _manualSaveDir = dir.path;
    return _manualSaveDir!;
  }

  void _ensureInitialized() {
    if (!_initialized) {
      throw StateError('SaveMgr not initialized — call initialize() first');
    }
  }

  // -- auto-save -------------------------------------------------------

  /// Persist the current game state as an auto-save.
  ///
  /// Every call overwrites the previous auto-save file.
  Future<void> autoSave({
    required PlayerState playerState,
    required int currentFloor,
    Set<String> bossDefeated = const {},
    Set<String> npcTriggered = const {},
    Set<String> inventory = const {},
  }) async {
    _ensureInitialized();
    final path = await _getAutoSavePath();
    final file = File(path);
    final state = SaveState(
      currentFloor: currentFloor,
      playerState: playerState,
      timestamp: DateTime.now().toIso8601String(),
      bossDefeated: bossDefeated,
      npcTriggered: npcTriggered,
      inventory: inventory,
    );
    await file.writeAsString(jsonEncode(state.toJson()));
  }

  /// Load the most recent auto-save.
  ///
  /// Returns `null` when no auto-save file exists.
  Future<SaveState?> loadAutoSave() async {
    _ensureInitialized();
    final path = await _getAutoSavePath();
    final file = File(path);
    if (!await file.exists()) return null;
    final raw = await file.readAsString();
    final json = jsonDecode(raw) as Map<String, dynamic>;
    return SaveState.fromJson(json);
  }

  /// Whether a valid auto-save file currently exists.
  Future<bool> hasAutoSave() async {
    _ensureInitialized();
    final path = await _getAutoSavePath();
    return File(path).exists();
  }

  /// Delete the auto-save file.
  Future<void> deleteAutoSave() async {
    _ensureInitialized();
    final path = await _getAutoSavePath();
    final file = File(path);
    if (await file.exists()) {
      await file.delete();
    }
  }

  // -- manual save (slot-based) ----------------------------------------

  /// Save to a manual slot (1-based index).
  ///
  /// Throws [ArgumentError] if [slot] is outside `1..maxManualSlots`.
  Future<void> manualSave(
    int slot,
    PlayerState state,
    int floor, {
    Set<String> bossDefeated = const {},
    Set<String> npcTriggered = const {},
    Set<String> inventory = const {},
  }) async {
    _ensureInitialized();
    if (slot < 1 || slot > maxManualSlots) {
      throw ArgumentError(
        'Invalid save slot: $slot (must be 1..$maxManualSlots)',
      );
    }
    final dir = await _getManualSaveDir();
    final path = '$dir/slot_$slot.json';
    final data = {
      'floor': floor,
      'player': state.toJson(),
      'timestamp': DateTime.now().toIso8601String(),
      'bossDefeated': bossDefeated.toList(),
      'npcTriggered': npcTriggered.toList(),
      'inventory': inventory.toList(),
    };
    final file = File(path);
    await file.writeAsString(jsonEncode(data));
  }

  /// Load a manual save from the given slot.
  ///
  /// Returns `null` when the slot is empty or corrupted.
  /// Out-of-range slots silently return `null`.
  Future<SaveState?> loadSave(int slot) async {
    _ensureInitialized();
    if (slot < 1 || slot > maxManualSlots) return null;
    final dir = await _getManualSaveDir();
    final path = '$dir/slot_$slot.json';
    final file = File(path);
    if (!await file.exists()) return null;
    try {
      final raw = await file.readAsString();
      final json = jsonDecode(raw) as Map<String, dynamic>;
      return SaveState.fromJson(json);
    } catch (_) {
      return null;
    }
  }

  /// List all non-empty manual save slots.
  ///
  /// Returns a map of slot number → [SaveState] for slots that exist.
  Future<Map<int, SaveState>> listSaveSlots() async {
    _ensureInitialized();
    final result = <int, SaveState>{};
    for (var i = 1; i <= maxManualSlots; i++) {
      final slot = await loadSave(i);
      if (slot != null) {
        result[i] = slot;
      }
    }
    return result;
  }

  /// Check whether a specific manual slot is occupied.
  Future<bool> hasSave(int slot) async {
    _ensureInitialized();
    if (slot < 1 || slot > maxManualSlots) return false;
    final dir = await _getManualSaveDir();
    final path = '$dir/slot_$slot.json';
    return File(path).exists();
  }

  /// Delete a manual save slot.
  ///
  /// Silently ignores out-of-range slots.
  Future<void> deleteSave(int slot) async {
    _ensureInitialized();
    if (slot < 1 || slot > maxManualSlots) return;
    final dir = await _getManualSaveDir();
    final path = '$dir/slot_$slot.json';
    final file = File(path);
    if (await file.exists()) {
      await file.delete();
    }
  }

  /// Clear all manual save slots.
  Future<void> clearAllSaves() async {
    _ensureInitialized();
    for (var i = 1; i <= maxManualSlots; i++) {
      await deleteSave(i);
    }
  }

  /// Clear the auto-save and all manual saves.
  Future<void> clearAll() async {
    _ensureInitialized();
    await deleteAutoSave();
    await clearAllSaves();
  }

  /// Get metadata for a manual save slot (floor, timestamp, level, hp).
  ///
  /// Returns `null` if the slot is empty.
  Future<Map<String, dynamic>?> getSaveMetadata(int slot) async {
    _ensureInitialized();
    final save = await loadSave(slot);
    if (save == null) return null;
    return {
      'floor': save.currentFloor,
      'timestamp': save.timestamp,
      'level': save.playerState.level,
      'hp': save.playerState.hp,
    };
  }
}
