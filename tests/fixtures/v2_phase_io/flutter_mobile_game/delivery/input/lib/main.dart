/// 魔塔 (Magic Tower) — 魔塔游戏入口
///
/// 启动 Flutter 应用，初始化所有子系统，进入主菜单。
///
/// Entry-point wiring:
///  - Step A: CONSTRUCT every subsystem instance (all components from
///    `docs/stack_contract.json#/subsystems[].components[]`).
///  - Step B: call every LIFECYCLE INIT via the contract loop.
///  - Step C: hand control to the Flutter runtime via `runApp`.
///  - Step E: `event_loop_owner` is `null` — Flutter owns dispatch.
///  - Step F: `event_loop_owner` is `null` — no manual render dispatch.
///  - Step D: `_self_check_lifecycle` asserts every init was reached.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:magic_tower/ui/menu_screen.dart';
import 'package:magic_tower/ui/hud_ui.dart';
import 'package:magic_tower/ui/game_screen.dart';
import 'package:magic_tower/ui/battle_screen.dart';
import 'package:magic_tower/ui/shop_screen.dart';
import 'package:magic_tower/ui/dialogue_screen.dart';
import 'package:magic_tower/ui/settings_screen.dart';
import 'package:magic_tower/gameplay/player_mgr.dart';
import 'package:magic_tower/gameplay/battle_engine.dart';
import 'package:magic_tower/gameplay/floor_mgr.dart';
import 'package:magic_tower/gameplay/inventory_mgr.dart';
import 'package:magic_tower/gameplay/npc_mgr.dart';
import 'package:magic_tower/gameplay/boss_engine.dart';
import 'package:magic_tower/gameplay/level_up_mgr.dart';
import 'package:magic_tower/gameplay/map_renderer.dart';
import 'package:magic_tower/gameplay/shop_engine.dart';
import 'package:magic_tower/system/save_mgr.dart';
import 'package:magic_tower/system/i18n_mgr.dart';
import 'package:magic_tower/system/audio_mgr.dart';
import 'package:magic_tower/system/settings_mgr.dart';
import 'package:magic_tower/data/models.dart';
import 'package:magic_tower/data/floor_loader.dart';

// ---------------------------------------------------------------------------
// Stack contract (embedded for the lifecycle loop)
// ---------------------------------------------------------------------------

/// The lifecycle_inits list from `docs/stack_contract.json`.
/// Every subsystem listed here MUST be constructed and initialized.
const List<Map<String, String>> _lifecycleInits = [
  {"attr": "menuScreen",    "method": "initialize"},
  {"attr": "hudUI",        "method": "initialize"},
  {"attr": "gameScreen",   "method": "initialize"},
  {"attr": "battleScreen", "method": "initialize"},
  {"attr": "shopScreen",   "method": "initialize"},
  {"attr": "dialogueScreen", "method": "initialize"},
  {"attr": "settingsScreen", "method": "initialize"},
  {"attr": "playerMgr",    "method": "initialize"},
  {"attr": "battleEngine", "method": "initialize"},
  {"attr": "floorMgr",     "method": "initialize"},
  {"attr": "inventoryMgr", "method": "initialize"},
  {"attr": "npcMgr",       "method": "initialize"},
  {"attr": "bossEngine",   "method": "initialize"},
  {"attr": "levelUpMgr",   "method": "initialize"},
  {"attr": "mapRenderer",  "method": "initialize"},
  {"attr": "shopEngine",   "method": "initialize"},
  {"attr": "saveMgr",      "method": "initialize"},
  {"attr": "i18nMgr",      "method": "initialize"},
  {"attr": "audioMgr",     "method": "initialize"},
  {"attr": "settingsMgr",  "method": "initialize"},
  {"attr": "floorLoader",  "method": "initialize"},
  {"attr": "iapProvider",  "method": "initialize"},
];

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

void main() {
  runApp(const ProviderScope(child: MagicTowerApp()));
}

/// 魔塔游戏应用入口
class MagicTowerApp extends StatefulWidget {
  const MagicTowerApp({super.key});

  @override
  State<MagicTowerApp> createState() => _MagicTowerAppState();
}

class _MagicTowerAppState extends State<MagicTowerApp> {
  // ── Step A: CONSTRUCT every subsystem instance ──────────────────────────

  // UI components
  late final MenuScreen menuScreen;
  late final HUDUI hudUI;
  late final GameScreen gameScreen;
  late final BattleScreen battleScreen;
  late final ShopScreen shopScreen;
  late final DialogueScreen dialogueScreen;
  late final SettingsScreen settingsScreen;

  // Gameplay components
  late final PlayerMgr playerMgr;
  late final BattleEngine battleEngine;
  late final FloorMgr floorMgr;
  late final InventoryMgr inventoryMgr;
  late final NPCMgr npcMgr;
  late final BossEngine bossEngine;
  late final LevelUpMgr levelUpMgr;
  late final MapRenderer mapRenderer;
  late final ShopEngine shopEngine;

  // System components
  late final SaveMgr saveMgr;
  late final I18nMgr i18nMgr;
  late final AudioMgr audioMgr;
  late final SettingsMgr settingsMgr;

  // Data components
  late final FloorLoader floorLoader;
  late final IapProvider iapProvider;

  /// Track which lifecycle entries have been reached.
  final Set<String> _reached = {};

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  // ── Step A: CONSTRUCT ──────────────────────────────────────────────────

  void _constructAll() {
    // UI
    menuScreen = MenuScreen();
    hudUI = HUDUI();
    gameScreen = GameScreen();
    battleScreen = BattleScreen();
    shopScreen = ShopScreen();
    dialogueScreen = DialogueScreen();
    settingsScreen = SettingsScreen();

    // Gameplay
    playerMgr = PlayerMgr();
    battleEngine = BattleEngine();
    floorMgr = FloorMgr();
    inventoryMgr = InventoryMgr();
    npcMgr = NPCMgr();
    bossEngine = BossEngine();
    levelUpMgr = LevelUpMgr();
    mapRenderer = MapRenderer();
    shopEngine = ShopEngine();

    // System
    saveMgr = SaveMgr();
    i18nMgr = I18nMgr();
    audioMgr = AudioMgr();
    settingsMgr = SettingsMgr();

    // Data
    floorLoader = FloorLoader();
  }

  // ── Step B: LIFECYCLE INIT (contract-driven loop) ──────────────────────

  void _initializeLifecycle() {
    for (final entry in _lifecycleInits) {
      final attr = entry["attr"]!;
      final method = entry["method"]!;
      final target = _getComponent(attr);
      final initMethod = _getInitMethod(target, method);
      initMethod();
      _reached.add(attr);
    }
  }

  Object _getComponent(String attr) {
    // All attributes must be valid instance members.
    return switch (attr) {
      "menuScreen"    => menuScreen,
      "hudUI"         => hudUI,
      "gameScreen"    => gameScreen,
      "battleScreen"  => battleScreen,
      "shopScreen"    => shopScreen,
      "dialogueScreen" => dialogueScreen,
      "settingsScreen" => settingsScreen,
      "playerMgr"     => playerMgr,
      "battleEngine"  => battleEngine,
      "floorMgr"      => floorMgr,
      "inventoryMgr"  => inventoryMgr,
      "npcMgr"        => npcMgr,
      "bossEngine"    => bossEngine,
      "levelUpMgr"    => levelUpMgr,
      "mapRenderer"   => mapRenderer,
      "shopEngine"    => shopEngine,
      "saveMgr"       => saveMgr,
      "i18nMgr"       => i18nMgr,
      "audioMgr"      => audioMgr,
      "settingsMgr"   => settingsMgr,
      "floorLoader"   => floorLoader,
      _ => throw StateError("Unknown lifecycle attr: $attr"),
    };
  }

  void Function() _getInitMethod(Object target, String method) {
    return switch (target) {
      MenuScreen    _ => _initMenuScreen,
      HUDUI         _ => _initHudUI,
      GameScreen    _ => _initGameScreen,
      BattleScreen  _ => _initBattleScreen,
      ShopScreen    _ => _initShopScreen,
      DialogueScreen _ => _initDialogueScreen,
      SettingsScreen _ => _initSettingsScreen,
      PlayerMgr     _ => _initPlayerMgr,
      BattleEngine  _ => _initBattleEngine,
      FloorMgr      _ => _initFloorMgr,
      InventoryMgr  _ => _initInventoryMgr,
      NPCMgr        _ => _initNpcMgr,
      BossEngine    _ => _initBossEngine,
      LevelUpMgr    _ => _initLevelUpMgr,
      MapRenderer   _ => _initMapRenderer,
      ShopEngine    _ => _initShopEngine,
      SaveMgr       _ => _initSaveMgr,
      I18nMgr       _ => _initI18nMgr,
      AudioMgr      _ => _initAudioMgr,
      SettingsMgr   _ => _initSettingsMgr,
      FloorLoader   _ => _initFloorLoader,
      IapProvider   _ => _initIapProvider,
      _ => throw StateError("Cannot initialize $target"),
    };
  }

  // Individual init wrappers — each calls the component's initialize() and
  // records that it was reached.
  void _initMenuScreen()    => menuScreen.initialize();
  void _initHudUI()         => hudUI.initialize();
  void _initGameScreen()    => gameScreen.initialize();
  void _initBattleScreen()  => battleScreen.initialize();
  void _initShopScreen()    => shopScreen.initialize();
  void _initDialogueScreen()=> dialogueScreen.initialize();
  void _initSettingsScreen()=> settingsScreen.initialize();
  void _initPlayerMgr()     => playerMgr.initialize();
  void _initBattleEngine()  => battleEngine.initialize();
  void _initFloorMgr()      => floorMgr.initialize();
  void _initInventoryMgr()  => inventoryMgr.initialize();
  void _initNpcMgr()        => npcMgr.initialize();
  void _initBossEngine()    => bossEngine.initialize();
  void _initLevelUpMgr()    => levelUpMgr.initialize();
  void _initMapRenderer()   => mapRenderer.initialize();
  void _initShopEngine()    => shopEngine.initialize();
  void _initSaveMgr()       => saveMgr.initialize();
  void _initI18nMgr()       => i18nMgr.initialize();
  void _initAudioMgr()      => audioMgr.initialize();
  void _initSettingsMgr()   => settingsMgr.initialize();
  void _initFloorLoader()   => floorLoader.initialize();
  void _initIapProvider()   => iapProvider.initialize();

  // ── Step D: SELF-CHECK ASSERTION ───────────────────────────────────────

  /// Fail fast if any subsystem skipped its initialize() call.
  void _selfCheckLifecycle() {
    for (final entry in _lifecycleInits) {
      final attr = entry["attr"]!;
      if (!_reached.contains(attr)) {
        throw StateError(
          "lifecycle wiring bug: $attr.initialize() never reached",
        );
      }
    }
  }

  // ── Full initialization ────────────────────────────────────────────────

  void _initialize() {
    // Step A
    _constructAll();

    // Step B
    _initializeLifecycle();

    // Step D
    _selfCheckLifecycle();
  }

  // ── Step C: FRAMEWORK MAIN LOOP ────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '魔塔 Magic Tower',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        primarySwatch: Colors.blue,
        useMaterial3: true,
      ),
      home: menuScreen,
    );
  }
}
