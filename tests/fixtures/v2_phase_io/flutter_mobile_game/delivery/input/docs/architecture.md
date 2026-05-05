# 魔塔 (Magic Tower) — 架构设计文档

## 1 概述

本架构文档描述了一款商用级魔塔（Magic Tower）手机游戏 APP 的系统架构。游戏采用经典回合制 RPG 玩法，基于 Flutter 3.x + Dart 跨平台开发，支持 Android 8.0+ 与 iOS 13+。系统划分为四个子系统：UI 子系统、游戏逻辑子系统、系统服务子系统和数据子系统。

```mermaid
C4Context
  title 魔塔系统上下文
  Person(player, "玩家", "在移动设备上玩魔塔游戏的用户")
  System(magic_tower, "魔塔 APP", "Flutter 跨平台移动游戏\n支持 Android 8.0+ / iOS 13+")
  System_Ext(app_store, "应用商店", "Google Play / App Store\n用于分发和更新")
  System_Ext(local_storage, "本地存储", "设备本地文件系统\n用于存档和配置")
  
  Rel(player, magic_tower, "玩游戏")
  Rel(magic_tower, app_store, "上架分发")
  Rel(magic_tower, local_storage, "读写存档")
```

## 2 技术栈选型

| 层面 | 技术选型 | 理由 |
|------|---------|------|
| 跨平台框架 | Flutter 3.x | 单一代码库同时编译 Android 和 iOS，性能接近原生 |
| 编程语言 | Dart | 类型安全、AOT 编译性能好，与 Flutter 深度集成 |
| 状态管理 | Riverpod | 编译时安全、测试友好、社区推荐 |
| 持久化 | path_provider + JSON 序列化 | 轻量级本地文件存储，无需数据库依赖 |
| 国际化 | flutter_localizations + 自定义 i18n | Flutter 原生支持，配合 JSON 资源文件 |
| 音频 | flutter_audio_player (占位) | BGM/SFX 播放占位实现 |
| 内购 | in_app_purchase (占位) | Flutter 官方内购插件接口，mock 实现 |

## 3 子系统架构

```mermaid
C4Container
  title 魔塔容器架构
  Container(game_app, "魔塔游戏应用", "Flutter App", "包含所有游戏 UI、逻辑、系统和数据子系统")
  
  Container_Boundary(ui_boundary, "UI 子系统", "所有用户界面和交互") {
    Component(menu_ui, "主菜单界面", "启动画面 + 主菜单\n开始/继续/设置/关于")
    Component(hud_ui, "HUD 组件", "游戏内 HUD\n显示四维+楼层+操作按钮")
    Component(game_ui, "游戏主界面", "地图渲染 + 玩家移动\n操作按钮 + 事件处理")
    Component(battle_ui, "战斗界面", "回合制战斗动画\n伤害计算展示")
    Component(shop_ui, "商店界面", "道具购买界面\n金币扣除逻辑")
    Component(dialogue_ui, "对话界面", "NPC 剧情对话\n多页滚动显示")
    Component(settings_ui, "设置界面", "音量/语言/清除存档")
  }
  
  Container_Boundary(gameplay_boundary, "游戏逻辑子系统", "核心玩法和规则引擎") {
    Component(player_mgr, "玩家管理器", "HP/ATK/DEF/Gold/EXP/Lv\n升级逻辑")
    Component(battle_engine, "战斗引擎", "回合制伤害计算\n战斗流程控制")
    Component(floor_mgr, "楼层管理器", "11×11 地图管理\n楼层切换逻辑")
    Component(inventory_mgr, "背包管理器", "道具拾取/使用\n钥匙/血瓶/宝石")
    Component(npc_mgr, "NPC 管理器", "剧情对话管理\n线索提示")
    Component(boss_engine, "BOSS 引擎", "多阶段 BOSS 战斗\n阶段转换逻辑")
    Component(level_up_mgr, "升级管理器", "EXP 升级公式\n属性提升")
    Component(map_renderer, "地图渲染器", "Tile 渲染逻辑\n颜色占位")
    Component(shop_engine, "商店引擎", "商品列表管理\n购买流程")
  }
  
  Container_Boundary(system_boundary, "系统服务子系统", "跨切面服务") {
    Component(save_mgr, "存档管理器", "自动存档/手动存档\nJSON 文件读写")
    Component(i18n_mgr, "国际化管理器", "中英文切换\ni18n JSON 加载")
    Component(audio_mgr, "音频管理器", "BGM/SFX 音量控制\n播放占位")
    Component(settings_mgr, "设置管理器", "设置持久化\n配置管理")
  }
  
  Container_Boundary(data_boundary, "数据子系统", "数据模型和加载") {
    Component(models, "数据模型", "PlayerState/Item/Floor等\n核心数据结构")
    Component(floor_loader, "楼层数据加载器", "floor_*.json 解析\n地图数据驱动")
  }
  
  Rel(game_app, ui_boundary, "使用")
  Rel(game_app, gameplay_boundary, "使用")
  Rel(game_app, system_boundary, "使用")
  Rel(game_app, data_boundary, "使用")
  
  Rel(ui_boundary, gameplay_boundary, "触发事件")
  Rel(gameplay_boundary, system_boundary, "请求服务")
  Rel(gameplay_boundary, data_boundary, "读取数据")
  Rel(system_boundary, data_boundary, "持久化数据")
```

## 4 模块依赖关系图

```mermaid
flowchart TD
  subgraph ui ["UI 子系统"]
    menu_ui
    hud_ui
    game_ui
    battle_ui
    shop_ui
    dialogue_ui
    settings_ui
  end
  
  subgraph gameplay ["游戏逻辑子系统"]
    player_mgr
    battle_engine
    floor_mgr
    inventory_mgr
    npc_mgr
    boss_engine
    level_up_mgr
    map_renderer
    shop_engine
  end
  
  subgraph system ["系统服务子系统"]
    save_mgr
    i18n_mgr
    audio_mgr
    settings_mgr
  end
  
  subgraph data ["数据子系统"]
    models
    floor_loader
  end
  
  menu_ui --> hud_ui
  menu_ui --> settings_ui
  game_ui --> hud_ui
  game_ui --> player_mgr
  game_ui --> floor_mgr
  game_ui --> inventory_mgr
  game_ui --> map_renderer
  game_ui --> npc_mgr
  battle_ui --> battle_engine
  battle_ui --> player_mgr
  battle_ui --> boss_engine
  shop_ui --> shop_engine
  shop_ui --> player_mgr
  dialogue_ui --> npc_mgr
  settings_ui --> settings_mgr
  settings_ui --> i18n_mgr
  settings_ui --> audio_mgr
  
  battle_engine --> player_mgr
  battle_engine --> boss_engine
  floor_mgr --> floor_loader
  floor_mgr --> models
  inventory_mgr --> models
  npc_mgr --> models
  boss_engine --> player_mgr
  boss_engine --> battle_engine
  level_up_mgr --> player_mgr
  map_renderer --> floor_mgr
  map_renderer --> models
  shop_engine --> player_mgr
  
  save_mgr --> models
  save_mgr --> floor_mgr
  i18n_mgr --> models
  audio_mgr --> models
  settings_mgr --> models
  
  floor_loader --> models
```

## 5 组件交互流程

### 5.1 启动与初始化流程

```mermaid
sequenceDiagram
    participant Main
    participant Menu as MenuScreen
    participant HUD as HUDUI
    participant Scene as GameScreen
    participant Battle as BattleScreen
    participant Shop as ShopScreen
    participant Dialog as DialogueScreen
    participant Settings as SettingsScreen
    participant Player as PlayerMgr
    participant BattleEng as BattleEngine
    participant Floor as FloorMgr
    participant Inv as InventoryMgr
    participant NPC as NPCMgr
    participant Boss as BossEngine
    participant Level as LevelUpMgr
    participant Map as MapRenderer
    participant ShopEng as ShopEngine
    participant Save as SaveMgr
    participant I18n as I18nMgr
    participant Audio as AudioMgr
    participant SetMgr as SettingsMgr
    participant Loader as FloorLoader

    Note over Main: 构造阶段 (Step A)
    Main->>Menu: __init__()
    Main->>HUD: __init__()
    Main->>Scene: __init__()
    Main->>Battle: __init__()
    Main->>Shop: __init__()
    Main->>Dialog: __init__()
    Main->>Settings: __init__()
    Main->>Player: __init__()
    Main->>BattleEng: __init__()
    Main->>Floor: __init__()
    Main->>Inv: __init__()
    Main->>NPC: __init__()
    Main->>Boss: __init__()
    Main->>Level: __init__()
    Main->>Map: __init__()
    Main->>ShopEng: __init__()
    Main->>Save: __init__()
    Main->>I18n: __init__()
    Main->>Audio: __init__()
    Main->>SetMgr: __init__()
    Main->>Loader: __init__()

    Note over Main: 生命周期初始化 (Step B)
    Main->>Menu: initialize()
    Main->>HUD: initialize()
    Main->>Scene: initialize()
    Main->>Battle: initialize()
    Main->>Shop: initialize()
    Main->>Dialog: initialize()
    Main->>Settings: initialize()
    Main->>Player: initialize()
    Main->>BattleEng: initialize()
    Main->>Floor: initialize()
    Main->>Inv: initialize()
    Main->>NPC: initialize()
    Main->>Boss: initialize()
    Main->>Level: initialize()
    Main->>Map: initialize()
    Main->>ShopEng: initialize()
    Main->>Save: initialize()
    Main->>I18n: initialize()
    Main->>Audio: initialize()
    Main->>SetMgr: initialize()

    Note over Main: 主循环启动 (Step C)
    Main->>Main: Flutter app.run()
```

### 5.2 游戏主循环流程

```mermaid
sequenceDiagram
    participant Player as 玩家输入
    participant GameUI as GameUI
    participant FloorMgr as FloorMgr
    participant PlayerMgr as PlayerMgr
    participant Battle as BattleEngine
    participant Save as SaveMgr
    
    Player->>GameUI: 按下方向键
    GameUI->>FloorMgr: movePlayer(direction)
    FloorMgr->>FloorMgr: 检查 Tile 类型
    
    alt 地板
        FloorMgr-->>GameUI: 移动成功
    else 墙壁/门
        FloorMgr-->>GameUI: 移动失败
    else 怪物
        FloorMgr->>Battle: startCombat(monster)
        Battle->>PlayerMgr: calculateDamage()
        Battle-->>GameUI: 战斗结果
        GameUI->>GameUI: 显示战斗界面
        alt 胜利
            Battle->>PlayerMgr: applyVictory()
            Battle->>Save: autoSave()
        else 失败
            Battle->>PlayerMgr: handleDeath()
            Battle->>Save: autoSave()
        end
    else 道具
        FloorMgr->>PlayerMgr: pickupItem(item)
        FloorMgr-->>GameUI: 道具拾取
    else NPC
        FloorMgr->>GameUI: showDialogue(npc)
    else 楼梯
        FloorMgr->>FloorMgr: switchFloor(direction)
        FloorMgr->>Save: autoSave()
    end
```

### 5.3 战斗流程

```mermaid
sequenceDiagram
    participant UI as BattleUI
    participant Engine as BattleEngine
    participant Player as PlayerMgr
    participant Boss as BossEngine
    
    UI->>Engine: startCombat(monster)
    Engine->>Player: getPlayerStats()
    
    loop 每回合
        Engine->>Player: calcPlayerDamage(monster)
        Player-->>Engine: 玩家造成伤害
        Engine->>Player: calcMonsterDamage(player)
        Player-->>Engine: 怪物造成伤害
        
        alt 玩家回合结束
            alt 怪物 HP ≤ 0
                Engine->>Player: applyVictoryRewards()
                Engine->>Boss: checkBossPhaseChange()
                Engine-->>UI: 玩家胜利
            else 玩家 HP ≤ 0
                Engine->>Player: handleDeath()
                Engine-->>UI: 玩家死亡
            end
        end
    end
```

### 5.4 存档流程

```mermaid
sequenceDiagram
    participant Game as 游戏逻辑
    participant Save as SaveMgr
    participant Data as 文件系统
    
    Game->>Save: autoSave(state)
    Save->>Save: 序列化 PlayerState + FloorState
    Save->>Data: writeJson(saveFile, data)
    Save-->>Game: 存档成功
    
    Note over Game: 手动存档时
    Game->>Save: manualSave(slot)
    Save->>Data: writeJson(saveSlot, data)
    Save-->>Game: 手动存档成功
    
    Note over Game: 加载存档时
    Game->>Save: loadSave(slot)
    Save->>Data: readJson(saveSlot)
    Data-->>Save: 原始数据
    Save->>Save: 反序列化
    Save-->>Game: PlayerState + FloorState
```

### 5.5 楼层切换流程

```mermaid
sequenceDiagram
    participant Player as 玩家
    participant GameUI as GameUI
    participant FloorMgr as FloorMgr
    participant Loader as FloorLoader
    participant Save as SaveMgr
    
    Player->>GameUI: 点击楼梯
    GameUI->>FloorMgr: requestFloorSwitch(direction)
    FloorMgr->>FloorMgr: 检查解锁条件
    
    alt 条件满足
        FloorMgr->>Loader: loadFloor(level)
        Loader->>Loader: 读取 floor_*.json
        Loader-->>FloorMgr: 地图数据
        FloorMgr->>FloorMgr: 更新当前楼层
        FloorMgr->>Save: autoSave()
        FloorMgr-->>GameUI: 切换成功
        GameUI->>GameUI: 重新渲染地图
    else 条件不满足
        FloorMgr-->>GameUI: 提示解锁条件
    end
```

## 6 数据模型

```mermaid
erDiagram
    PLAYER_STATE ||--o{ INVENTORY : has
    PLAYER_STATE ||--o{ SAVE_SLOT : saved_as
    FLOOR_DATA ||--o{ TILE : contains
    TILE ||--o{ ITEM : may_contain
    TILE ||--o{ MONSTER : may_contain
    TILE ||--o{ NPC : may_contain
    MONSTER ||--o{ BOSS_PHASE : has_phases
    
    PLAYER_STATE {
        int hp
        int atk
        int def
        int gold
        int exp
        int level
        Point2D position
    }
    
    INVENTORY {
        ItemType type
        int quantity
    }
    
    SAVE_SLOT {
        int slot_id
        string timestamp
        bool is_auto
    }
    
    FLOOR_DATA {
        int floor_id
        int width
        int height
        string unlock_condition
    }
    
    TILE {
        TileType type
        Color color
        string data_ref
    }
    
    ITEM {
        ItemType type
        string name
        int value
    }
    
    MONSTER {
        string name
        int hp
        int atk
        int def
        int exp_reward
        int gold_reward
    }
    
    NPC {
        string id
        string dialogue_id
        bool revealed
    }
    
    BOSS_PHASE {
        int phase_id
        int hp_threshold
        int atk
        int def
        string special
    }
```

## 7 子系统详细设计

### 7.1 UI 子系统 (ui)

| 组件 | 文件 | 职责 |
|------|------|------|
| MenuUI | `lib/ui/menu_screen.dart` | 启动画面 + 主菜单（开始/继续/设置/关于） |
| HUDWidget | `lib/ui/hud_ui.dart` | 游戏内 HUD：显示四维+楼层+操作按钮 |
| GameUI | `lib/ui/game_screen.dart` | 游戏主界面：地图渲染 + 玩家移动 + 事件处理 |
| BattleUI | `lib/ui/battle_screen.dart` | 战斗界面：回合制战斗动画 + 伤害展示 |
| ShopUI | `lib/ui/shop_screen.dart` | 商店界面：道具购买 + 金币扣除 |
| DialogueUI | `lib/ui/dialogue_screen.dart` | NPC 对话界面：多页滚动剧情显示 |
| SettingsUI | `lib/ui/settings_screen.dart` | 设置界面：音量/语言/清除存档 |

### 7.2 游戏逻辑子系统 (gameplay)

| 组件 | 文件 | 职责 |
|------|------|------|
| PlayerMgr | `lib/gameplay/player_mgr.dart` | 玩家状态管理：HP/ATK/DEF/Gold/EXP/Lv |
| BattleEngine | `lib/gameplay/battle_engine.dart` | 回合制伤害计算：max(ATK−DEF, 1) |
| FloorMgr | `lib/gameplay/floor_mgr.dart` | 11×11 地图管理 + 楼层切换逻辑 |
| InventoryMgr | `lib/gameplay/inventory_mgr.dart` | 道具拾取/使用：钥匙/血瓶/宝石 |
| NPCMgr | `lib/gameplay/npc_mgr.dart` | 剧情对话管理 + 线索提示 |
| BossEngine | `lib/gameplay/boss_engine.dart` | 多阶段 BOSS 战斗逻辑 |
| LevelUpMgr | `lib/gameplay/level_up_mgr.dart` | EXP 升级公式：50+Lv×30+Lv²×5 |
| MapRenderer | `lib/gameplay/map_renderer.dart` | Tile 渲染逻辑 + 颜色占位 |
| ShopEngine | `lib/gameplay/shop_engine.dart` | 商店商品管理 + 购买流程 |

### 7.3 系统服务子系统 (system)

| 组件 | 文件 | 职责 |
|------|------|------|
| SaveMgr | `lib/system/save_mgr.dart` | 自动存档/手动存档：JSON 文件读写 |
| I18nMgr | `lib/system/i18n_mgr.dart` | 中英文切换：i18n JSON 资源加载 |
| AudioMgr | `lib/system/audio_mgr.dart` | BGM/SFX 音量控制：播放占位 |
| SettingsMgr | `lib/system/settings_mgr.dart` | 设置持久化：配置管理 |

### 7.4 数据子系统 (data)

| 组件 | 文件 | 职责 |
|------|------|------|
| Models | `lib/data/models.dart` | 核心数据结构：PlayerState/Item/Floor 等 |
| FloorLoader | `lib/data/floor_loader.dart` | floor_*.json 解析：地图数据驱动 |

## 8 关键设计决策

### 8.1 为什么选择 Riverpod

Riverpod 提供编译时安全的状态管理，比 Provider 更简洁。对于魔塔这种状态更新频繁的游戏，Riverpod 的 `Notifier` 模式可以 cleanly 管理玩家状态、楼层状态和 UI 状态的变化。

### 8.2 数据驱动地图

所有楼层数据通过 `floor_*.json` 文件驱动，而非硬编码。这使得：
- 关卡设计可以独立于代码迭代
- 新增楼层只需添加 JSON 文件
- 测试时可以用 mock JSON 数据

### 8.3 占位资源策略

使用纯颜色矩形 + Material Icons 作为美术占位，但代码中预留 asset 槽位：
- `assets/images/` — 角色、怪物、道具精灵图
- `assets/audio/` — BGM 和 SFX 文件
- `assets/data/` — floor_*.json 和 i18n.json

### 8.4 存档策略

- **自动存档**：楼层切换后、战斗结束后自动触发
- **手动存档**：3 个独立槽位，支持保存/读取/删除
- **文件格式**：JSON，使用 `path_provider` 获取应用文档目录

### 8.5 内购占位

使用 `in_app_purchase` 插件接口，但实现为 mock 版本：
- 点击按钮弹出确认弹窗
- 模拟支付成功/取消
- 成功后增加金币，失败不阻塞游戏

## 9 性能优化策略

- **60 FPS 保证**：使用 Flutter 的 `RepaintBoundary` 隔离 HUD 重绘区域
- **冷启动优化**：预加载 i18n 资源和第一层地图数据
- **内存管理**：楼层切换时释放上一地图数据，保持内存 < 200MB
- **渲染优化**：地图 Tile 使用批量绘制，避免逐格渲染

## 10 测试策略

### 单元测试
- 战斗公式测试：验证 max(ATK−DEF, 1) 公式在各种攻防组合下的正确性
- 升级公式测试：验证 EXP 升级公式在不同等级下的正确性
- 存档读写测试：验证 JSON 序列化/反序列化的正确性
- 道具使用测试：验证钥匙开门、血瓶回血等逻辑

### E2E 集成测试 (scenarios/)
- 主线流程：开局→上 2 楼→死亡复活
- 商店购买：进入商店→购买道具→金币扣除验证
- BOSS 战：进入 BOSS 层→多阶段战斗→击败 BOSS

## 11 启动序列

```mermaid
sequenceDiagram
    participant Main
    participant Data as Data Subsystem
    participant System as System Subsystem
    participant Gameplay as Gameplay Subsystem
    participant UI as UI Subsystem
    
    Note over Main: 构造阶段 (Step A)
    Main->>Data: __init__()
    Main->>System: __init__()
    Main->>Gameplay: __init__()
    Main->>UI: __init__()
    
    Note over Main: 生命周期初始化 (Step B)
    Main->>Data: initialize()
    Main->>System: initialize()
    Main->>Gameplay: initialize()
    Main->>UI: initialize()
    
    Note over Main: 主循环启动 (Step C)
    Main->>UI: app.run()
```
