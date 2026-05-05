/// Riverpod providers for the Magic Tower game.
///
/// Exposes game state, settings, and subsystem instances as
/// `StateNotifierProvider` and `Provider` so that UI widgets
/// can read / write game state reactively.

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'data/models.dart';
import 'gameplay/player_mgr.dart';
import 'gameplay/battle_engine.dart';
import 'gameplay/floor_mgr.dart';
import 'gameplay/inventory_mgr.dart';
import 'gameplay/npc_mgr.dart';
import 'gameplay/boss_engine.dart';
import 'gameplay/level_up_mgr.dart';
import 'gameplay/map_renderer.dart';
import 'gameplay/shop_engine.dart';
import 'system/save_mgr.dart';
import 'system/i18n_mgr.dart';
import 'system/audio_mgr.dart';
import 'system/settings_mgr.dart';
import 'system/iap_provider.dart';
import 'data/floor_loader.dart';

// ─────────────────────────────────────────────────────────────────────────────
// GameStateNotifier
// ─────────────────────────────────────────────────────────────────────────────

/// Reactive game state that drives the UI.
///
/// All mutable game state flows through this notifier; UI widgets
/// read from it via `ref.read(gameStateProvider)` or
/// `ref.watch(gameStateProvider)`.
class GameStateNotifier extends StateNotifier<GameState> {
  GameStateNotifier({
    required this.playerMgr,
    required this.battleEngine,
    required this.floorMgr,
    required this.inventoryMgr,
    required this.npcMgr,
    required this.bossEngine,
    required this.levelUpMgr,
    required this.mapRenderer,
    required this.shopEngine,
    required this.saveMgr,
    required this.i18nMgr,
    required this.audioMgr,
    required this.settingsMgr,
    required this.floorLoader,
    required this.iapProvider,
  }) : super(GameState());

  final PlayerMgr playerMgr;
  final BattleEngine battleEngine;
  final FloorMgr floorMgr;
  final InventoryMgr inventoryMgr;
  final NPCMgr npcMgr;
  final BossEngine bossEngine;
  final LevelUpMgr levelUpMgr;
  final MapRenderer mapRenderer;
  final ShopEngine shopEngine;
  final SaveMgr saveMgr;
  final I18nMgr i18nMgr;
  final AudioMgr audioMgr;
  final SettingsMgr settingsMgr;
  final FloorLoader floorLoader;
  final IapProvider iapProvider;

  /// Start a new game at floor 1.
  Future<void> startNewGame() async {
    playerMgr.initialize(
      hp: 100, maxHp: 100, atk: 10, def: 10, gold: 0, exp: 0, level: 1,
    );
    floorMgr.initialize(
      mapSize: 11, minFloor: 1, maxFloor: 10,
      startFloor: 1, startPosX: 5, startPosY: 10,
    );
    state = state.copyWith(
      player: playerMgr.toPlayerState(),
      currentFloorIndex: 0,
      isBattleActive: false,
      isInShop: false,
      isInDialogue: false,
      isGameOver: false,
      isPaused: false,
    );
    saveMgr.autoSave(
      playerState: playerMgr.toPlayerState(),
      currentFloor: floorMgr.currentFloor,
    ).then((_) => null);
  }

  /// Move the player in [dx], [dy] direction.
  Future<void> movePlayer(int dx, int dy) async {
    if (state.isBattleActive || state.isInShop || state.isInDialogue) return;
    if (!floorMgr.movePlayer(dx, dy)) return;

    // Check for events at the new position
    final key = '${floorMgr.playerX},${floorMgr.playerY}';
    if (floorMgr.monsters.containsKey(key)) {
      _startBattle(key);
    } else if (floorMgr.npcs.containsKey(key)) {
      _startDialogue(key);
    } else if (floorMgr.items.containsKey(key)) {
      _pickupItem(key);
    }
  }

  void _startBattle(String key) {
    final monster = floorMgr.monsters[key];
    if (monster == null) return;
    state = state.copyWith(isBattleActive: true);
  }

  void _startDialogue(String key) {
    final npcId = floorMgr.npcs[key];
    if (npcId == null) return;
    state = state.copyWith(
      isInDialogue: true,
      dialogueText: npcId,
    );
  }

  Future<void> _pickupItem(String key) async {
    final itemId = floorMgr.items[key];
    if (itemId == null) return;
    // In a full implementation this would add the item to inventory
    await floorMgr.removeItem(
      int.parse(key.split(',').first),
      int.parse(key.split(',').last),
    );
  }

  /// End battle and return to normal gameplay.
  void endBattle() {
    state = state.copyWith(
      isBattleActive: false,
      battleResult: null,
    );
  }

  /// Open / close the shop UI.
  void toggleShop() {
    state = state.copyWith(
      isInShop: !state.isInShop,
      isBattleActive: false,
    );
  }

  /// Close the dialogue UI.
  void closeDialogue() {
    state = state.copyWith(
      isInDialogue: false,
      dialogueText: '',
    );
  }

  /// Toggle pause.
  void togglePause() {
    state = state.copyWith(isPaused: !state.isPaused);
  }

  /// Go up one floor.
  Future<void> goUp() async {
    if (floorMgr.goUpFloor()) {
      state = state.copyWith(
        currentFloorIndex: floorMgr.currentFloor - 1,
      );
      await saveMgr.autoSave(
        playerState: playerMgr.toPlayerState(),
        currentFloor: floorMgr.currentFloor,
      );
    }
  }

  /// Go down one floor.
  Future<void> goDown() async {
    if (floorMgr.goDownFloor()) {
      state = state.copyWith(
        currentFloorIndex: floorMgr.currentFloor - 1,
      );
      await saveMgr.autoSave(
        playerState: playerMgr.toPlayerState(),
        currentFloor: floorMgr.currentFloor,
      );
    }
  }

  /// Save the current state to a manual slot.
  Future<void> manualSave(int slot) async {
    await saveMgr.manualSave(
      slot,
      playerMgr.toPlayerState(),
      floorMgr.currentFloor,
    );
  }

  /// Load a manual slot.
  Future<void> loadManualSave(int slot) async {
    final loaded = await saveMgr.loadSave(slot);
    if (loaded != null) {
      state = state.copyWith(
        player: loaded.playerState,
        currentFloorIndex: loaded.currentFloor - 1,
      );
    }
  }

  /// Switch language between 'zh' and 'en'.
  void switchLanguage() {
    final next = state.isInDialogue ? 'en' : 'zh';
    i18nMgr.currentLanguage = next;
    settingsMgr.setLanguage(next);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Providers
// ─────────────────────────────────────────────────────────────────────────────

/// Provides the [GameStateNotifier] instance.
final gameServiceProvider = StateNotifierProvider<GameStateNotifier, GameState>(
  (ref) {
    final playerMgr = PlayerMgr();
    final battleEngine = BattleEngine();
    final floorMgr = FloorMgr();
    final inventoryMgr = InventoryMgr();
    final npcMgr = NPCMgr();
    final bossEngine = BossEngine();
    final levelUpMgr = LevelUpMgr();
    final mapRenderer = MapRenderer();
    final shopEngine = ShopEngine();
    final saveMgr = SaveMgr();
    final i18nMgr = I18nMgr();
    final audioMgr = AudioMgr();
    final settingsMgr = SettingsMgr();
    final floorLoader = FloorLoader();
    final iapProvider = IapProvider();

    return GameStateNotifier(
      playerMgr: playerMgr,
      battleEngine: battleEngine,
      floorMgr: floorMgr,
      inventoryMgr: inventoryMgr,
      npcMgr: npcMgr,
      bossEngine: bossEngine,
      levelUpMgr: levelUpMgr,
      mapRenderer: mapRenderer,
      shopEngine: shopEngine,
      saveMgr: saveMgr,
      i18nMgr: i18nMgr,
      audioMgr: audioMgr,
      settingsMgr: settingsMgr,
      floorLoader: floorLoader,
      iapProvider: iapProvider,
    );
  },
);

/// Provides the IAP provider directly for UI access.
final iapProviderProvider = Provider<IapProvider>((ref) {
  return ref.read(gameServiceProvider).iapProvider;
});

/// Provides the current language code.
final languageProvider = Provider<String>((ref) {
  final game = ref.watch(gameServiceProvider);
  return game.dialogueText;
});

/// Provides the current floor number.
final currentFloorProvider = Provider<int>((ref) {
  final game = ref.read(gameServiceProvider);
  return game.currentFloorIndex + 1;
});

/// Provides the player HP.
final playerHpProvider = Provider<int>((ref) {
  final game = ref.read(gameServiceProvider);
  return game.player.hp;
});

/// Provides the player ATK.
final playerAtkProvider = Provider<int>((ref) {
  final game = ref.read(gameServiceProvider);
  return game.player.atk;
});

/// Provides the player DEF.
final playerDefProvider = Provider<int>((ref) {
  final game = ref.read(gameServiceProvider);
  return game.player.def;
});

/// Provides the player Gold.
final playerGoldProvider = Provider<int>((ref) {
  final game = ref.read(gameServiceProvider);
  return game.player.gold;
});

/// Provides the player EXP.
final playerExpProvider = Provider<int>((ref) {
  final game = ref.read(gameServiceProvider);
  return game.player.exp;
});

/// Provides the player Level.
final playerLevelProvider = Provider<int>((ref) {
  final game = ref.read(gameServiceProvider);
  return game.player.level;
});
