/// Core data models for the Magic Tower game.
///
/// Defines [PlayerState], [Item], [Tile], [Floor], [BattleResult],
/// [GameState], and [SaveData] — the structural backbone of the game.

library;

import 'dart:ui';

// ─────────────────────────────────────────────────────────────────────────────
// Direction
// ─────────────────────────────────────────────────────────────────────────────

/// Cardinal directions used for movement and map traversal.
enum Dir {
  up,
  down,
  left,
  right,
}

/// Extension providing geometric helpers on [Dir].
extension DirExtension on Dir {
  /// Offset vector for this direction.
  Offset get offset {
    switch (this) {
      case Dir.up:
        return const Offset(0, -1);
      case Dir.down:
        return const Offset(0, 1);
      case Dir.left:
        return const Offset(-1, 0);
      case Dir.right:
        return const Offset(1, 0);
    }
  }

  /// The opposite direction.
  Dir get opposite {
    switch (this) {
      case Dir.up:
        return Dir.down;
      case Dir.down:
        return Dir.up;
      case Dir.left:
        return Dir.right;
      case Dir.right:
        return Dir.left;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Point — lightweight 2-D coordinate
// ─────────────────────────────────────────────────────────────────────────────

/// Immutable 2-D point / coordinate.
class Point {
  final int x;
  final int y;

  const Point(this.x, this.y);

  /// Manhattan distance to another point.
  int distanceTo(Point other) => (x - other.x).abs() + (y - other.y).abs();

  /// Whether the two points are adjacent (distance == 1).
  bool isAdjacent(Point other) => distanceTo(other) == 1;

  /// Return a new point offset by (dx, dy).
  Point offset({int dx = 0, int dy = 0}) => Point(x + dx, y + dy);

  /// Direction from this point toward [target], or null if same point.
  Dir? directionTo(Point target) {
    final dx = target.x - x;
    final dy = target.y - y;
    if (dx == 0 && dy < 0) return Dir.up;
    if (dx == 0 && dy > 0) return Dir.down;
    if (dx < 0 && dy == 0) return Dir.left;
    if (dx > 0 && dy == 0) return Dir.right;
    return null;
  }

  // ── equality / toString ────────────────────────────────────────────────

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Point && x == other.x && y == other.y;

  @override
  int get hashCode => x.hashCode ^ (y.hashCode * 31);

  @override
  String toString() => 'Point($x, $y)';
}

// ─────────────────────────────────────────────────────────────────────────────
// Tile type enumeration
// ─────────────────────────────────────────────────────────────────────────────

/// Kinds of map tiles that can appear in a floor.
enum TileType {
  wall,
  floor,
  doorYellow,
  doorBlue,
  doorRed,
  stairUp,
  stairDown,
  playerStart,
  chest,
  keyYellow,
  keyBlue,
  keyRed,
  potionRed,
  potionBlue,
  gemRed,
  gemBlue,
  gemYellow,
  npc,
  shop,
  boss,
  hidden,
}

// ─────────────────────────────────────────────────────────────────────────────
// Tile
// ─────────────────────────────────────────────────────────────────────────────

/// A single cell on the game map.
class Tile {
  final TileType type;
  final bool walkable;

  Tile({
    required this.type,
    this.walkable = true,
  });

  /// Create a tile from a JSON-like map.
  factory Tile.fromMap(Map<String, dynamic> map) {
    final rawType = map['type'] as String?;
    final type = _tileTypeFromString(rawType ?? '');
    final walkable = map['walkable'] as bool? ?? (type == TileType.floor || type == TileType.playerStart);
    return Tile(type: type, walkable: walkable);
  }

  /// Serialise to a JSON-like map.
  Map<String, dynamic> toMap() => {
        'type': _tileTypeToString(type),
        'walkable': walkable,
      };

  // ── equality / hashCode ────────────────────────────────────────────────

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Tile && type == other.type && walkable == other.walkable;

  @override
  int get hashCode => type.hashCode ^ (walkable ? 1 : 0);

  @override
  String toString() => 'Tile($type, walkable=$walkable)';

  // ── helpers ────────────────────────────────────────────────────────────

  static TileType _tileTypeFromString(String s) {
    switch (s) {
      case 'wall':
        return TileType.wall;
      case 'floor':
        return TileType.floor;
      case 'doorYellow':
        return TileType.doorYellow;
      case 'doorBlue':
        return TileType.doorBlue;
      case 'doorRed':
        return TileType.doorRed;
      case 'stairUp':
        return TileType.stairUp;
      case 'stairDown':
        return TileType.stairDown;
      case 'playerStart':
        return TileType.playerStart;
      case 'chest':
        return TileType.chest;
      case 'keyYellow':
        return TileType.keyYellow;
      case 'keyBlue':
        return TileType.keyBlue;
      case 'keyRed':
        return TileType.keyRed;
      case 'potionRed':
        return TileType.potionRed;
      case 'potionBlue':
        return TileType.potionBlue;
      case 'gemRed':
        return TileType.gemRed;
      case 'gemBlue':
        return TileType.gemBlue;
      case 'gemYellow':
        return TileType.gemYellow;
      case 'npc':
        return TileType.npc;
      case 'shop':
        return TileType.shop;
      case 'boss':
        return TileType.boss;
      case 'hidden':
        return TileType.hidden;
      default:
        return TileType.floor;
    }
  }

  static String _tileTypeToString(TileType t) {
    switch (t) {
      case TileType.wall:
        return 'wall';
      case TileType.floor:
        return 'floor';
      case TileType.doorYellow:
        return 'doorYellow';
      case TileType.doorBlue:
        return 'doorBlue';
      case TileType.doorRed:
        return 'doorRed';
      case TileType.stairUp:
        return 'stairUp';
      case TileType.stairDown:
        return 'stairDown';
      case TileType.playerStart:
        return 'playerStart';
      case TileType.chest:
        return 'chest';
      case TileType.keyYellow:
        return 'keyYellow';
      case TileType.keyBlue:
        return 'keyBlue';
      case TileType.keyRed:
        return 'keyRed';
      case TileType.potionRed:
        return 'potionRed';
      case TileType.potionBlue:
        return 'potionBlue';
      case TileType.gemRed:
        return 'gemRed';
      case TileType.gemBlue:
        return 'gemBlue';
      case TileType.gemYellow:
        return 'gemYellow';
      case TileType.npc:
        return 'npc';
      case TileType.shop:
        return 'shop';
      case TileType.boss:
        return 'boss';
      case TileType.hidden:
        return 'hidden';
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Item type enumeration
// ─────────────────────────────────────────────────────────────────────────────

/// Types of items the player can carry.
enum ItemType {
  yellowKey,
  blueKey,
  redKey,
  redPotion,
  bluePotion,
  redGem,
  blueGem,
  yellowGem,
  none, // sentinel for "no item"
}

/// Serialisation helpers for [ItemType].
extension ItemTypeExt on ItemType {
  String get name {
    switch (this) {
      case ItemType.yellowKey:
        return 'yellowKey';
      case ItemType.blueKey:
        return 'blueKey';
      case ItemType.redKey:
        return 'redKey';
      case ItemType.redPotion:
        return 'redPotion';
      case ItemType.bluePotion:
        return 'bluePotion';
      case ItemType.redGem:
        return 'redGem';
      case ItemType.blueGem:
        return 'blueGem';
      case ItemType.yellowGem:
        return 'yellowGem';
      case ItemType.none:
        return 'none';
    }
  }

  static ItemType fromName(String name) {
    switch (name) {
      case 'yellowKey':
        return ItemType.yellowKey;
      case 'blueKey':
        return ItemType.blueKey;
      case 'redKey':
        return ItemType.redKey;
      case 'redPotion':
        return ItemType.redPotion;
      case 'bluePotion':
        return ItemType.bluePotion;
      case 'redGem':
        return ItemType.redGem;
      case 'blueGem':
        return ItemType.blueGem;
      case 'yellowGem':
        return ItemType.yellowGem;
      case 'none':
      default:
        return ItemType.none;
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Item
// ─────────────────────────────────────────────────────────────────────────────

/// A single inventory item.
class Item {
  final ItemType type;
  final int count;

  Item({
    required this.type,
    this.count = 1,
  });

  /// Create from a JSON-like map.
  factory Item.fromMap(Map<String, dynamic> map) {
    final type = ItemType.fromName(map['type'] as String? ?? 'none');
    final count = map['count'] as int? ?? 1;
    return Item(type: type, count: count);
  }

  /// Serialise to a JSON-like map.
  Map<String, dynamic> toMap() => {
        'type': type.name,
        'count': count,
      };

  // ── equality / hashCode ────────────────────────────────────────────────

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Item && type == other.type && count == other.count;

  @override
  int get hashCode => type.hashCode ^ (count * 31);

  @override
  String toString() => 'Item(${type.name} x$count)';
}

// ─────────────────────────────────────────────────────────────────────────────
// PlayerState
// ─────────────────────────────────────────────────────────────────────────────

/// Complete state of the player character.
class PlayerState {
  /// Current hit points.
  int hp;

  /// Attack power.
  int atk;

  /// Defence.
  int def;

  /// Gold coins.
  int gold;

  /// Experience points.
  int exp;

  /// Current level.
  int level;

  /// Current grid position.
  Point position;

  /// Index into the floors list.
  int currentFloor;

  /// Inventory.
  List<Item> inventory;

  /// Whether the player is alive.
  bool isAlive;

  PlayerState({
    this.hp = 100,
    this.atk = 10,
    this.def = 10,
    this.gold = 0,
    this.exp = 0,
    this.level = 1,
    this.position = const Point(0, 0),
    this.currentFloor = 0,
    this.inventory = const [],
    this.isAlive = true,
  });

  // ── mutations ──────────────────────────────────────────────────────────

  /// Deal [damage] to the player.
  void takeDamage(int damage) {
    hp -= damage;
    if (hp <= 0) isAlive = false;
  }

  /// Restore [amount] HP, capped at 100.
  void heal(int amount) {
    hp = (hp + amount).clamp(0, 100);
    if (hp > 0) isAlive = true;
  }

  /// Add gold.
  void addGold(int amount) {
    if (amount < 0) return;
    gold += amount;
  }

  /// Spend gold; throws if insufficient.
  void spendGold(int amount) {
    if (amount < 0 || gold < amount) {
      throw StateError('Not enough gold: have $gold, need $amount');
    }
    gold -= amount;
  }

  /// Add experience.
  void addExp(int amount) {
    if (amount < 0) return;
    exp += amount;
  }

  /// Move the player to a new grid position.
  void move(int x, int y) {
    position = Point(x, y);
  }

  /// Switch to a specific floor.
  void moveToFloor(int floorIndex) {
    currentFloor = floorIndex;
  }

  // ── serialisation ────────────────────────────────────────────────────

  /// Serialise to a JSON-like map.
  Map<String, dynamic> toMap() => {
        'hp': hp,
        'atk': atk,
        'def': def,
        'gold': gold,
        'exp': exp,
        'level': level,
        'x': position.x,
        'y': position.y,
        'floor': currentFloor,
        'inventory': inventory.map((i) => i.toMap()).toList(),
      };

  /// Reconstruct from a JSON-like map.
  factory PlayerState.fromMap(Map<String, dynamic> map) {
    final level = (map['level'] as int? ?? 1).clamp(1, 99);
    final hp = (map['hp'] as int? ?? 100).clamp(0, 100);
    return PlayerState(
      hp: hp,
      atk: map['atk'] as int? ?? 10,
      def: map['def'] as int? ?? 10,
      gold: map['gold'] as int? ?? 0,
      exp: map['exp'] as int? ?? 0,
      level: level,
      position: Point(
        map['x'] as int? ?? 0,
        map['y'] as int? ?? 0,
      ),
      currentFloor: map['floor'] as int? ?? 0,
      inventory: (map['inventory'] as List<dynamic>?)
              ?.map((e) => Item.fromMap(e as Map<String, dynamic>))
              .toList() ??
          [],
      isAlive: hp > 0,
    );
  }

  /// Shallow copy.
  PlayerState copy() {
    return PlayerState(
      hp: hp,
      atk: atk,
      def: def,
      gold: gold,
      exp: exp,
      level: level,
      position: Point(position.x, position.y),
      currentFloor: currentFloor,
      inventory: List.from(inventory),
      isAlive: isAlive,
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// MonsterState
// ─────────────────────────────────────────────────────────────────────────────

/// State of a monster encountered during gameplay.
class MonsterState {
  /// Unique identifier for the monster definition.
  final String defId;

  /// Display name.
  final String name;

  /// Current hit points.
  final int currentHp;

  /// Maximum hit points.
  final int maxHp;

  /// Attack power.
  final int atk;

  /// Defence.
  final int def;

  /// Experience points awarded on defeat.
  final int expReward;

  /// Gold coins awarded on defeat.
  final int goldReward;

  /// Whether this is a boss monster.
  final bool isBoss;

  MonsterState({
    this.defId = 'unknown',
    this.name = 'Unknown',
    this.currentHp = 0,
    this.maxHp = 0,
    this.atk = 0,
    this.def = 0,
    this.expReward = 0,
    this.goldReward = 0,
    this.isBoss = false,
  });

  /// Create from a JSON-like map.
  factory MonsterState.fromMap(Map<String, dynamic> map) {
    return MonsterState(
      defId: map['defId'] as String? ?? 'unknown',
      name: map['name'] as String? ?? 'Unknown',
      currentHp: map['currentHp'] as int? ?? 0,
      maxHp: map['maxHp'] as int? ?? 0,
      atk: map['atk'] as int? ?? 0,
      def: map['def'] as int? ?? 0,
      expReward: map['expReward'] as int? ?? 0,
      goldReward: map['goldReward'] as int? ?? 0,
      isBoss: map['isBoss'] as bool? ?? false,
    );
  }

  /// Serialise to a JSON-like map.
  Map<String, dynamic> toMap() => {
        'defId': defId,
        'name': name,
        'currentHp': currentHp,
        'maxHp': maxHp,
        'atk': atk,
        'def': def,
        'expReward': expReward,
        'goldReward': goldReward,
        'isBoss': isBoss,
      };

  // ── equality / hashCode ────────────────────────────────────────────────

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is MonsterState && defId == other.defId;

  @override
  int get hashCode => defId.hashCode;

  @override
  String toString() => 'MonsterState($name, HP: $currentHp/$maxHp)';
}

// ─────────────────────────────────────────────────────────────────────────────
// Floor
// ─────────────────────────────────────────────────────────────────────────────

/// A single floor (level) in the tower.
class Floor {
  /// Floor number / index (0 = ground floor).
  final int level;

  /// Display name for this floor.
  final String name;

  /// Width in tiles.
  final int width;

  /// Height in tiles.
  final int height;

  /// 2-D tile grid (row-major).
  final List<List<Tile>> tiles;

  /// Position of the up-stair tile (on this floor).
  final Point? stairUp;

  /// Position of the down-stair tile (on this floor).
  final Point? stairDown;

  /// Key type required to descend (null = no restriction).
  final ItemType? requiredKey;

  /// Whether the floor's boss has been defeated.
  bool bossDefeated;

  Floor({
    this.level = 0,
    this.name = 'Entrance',
    this.width = 11,
    this.height = 11,
    required this.tiles,
    this.stairUp,
    this.stairDown,
    this.requiredKey,
    this.bossDefeated = false,
  });

  // ── serialisation ────────────────────────────────────────────────────

  Map<String, dynamic> toMap() => {
        'level': level,
        'name': name,
        'width': width,
        'height': height,
        'tiles': tiles.map((row) => row.map((t) => t.toMap()).toList()).toList(),
        'stairUp': stairUp != null ? {'x': stairUp!.x, 'y': stairUp!.y} : null,
        'stairDown': stairDown != null ? {'x': stairDown!.x, 'y': stairDown!.y} : null,
        'requiredKey': requiredKey?.name,
        'bossDefeated': bossDefeated,
      };

  factory Floor.fromMap(Map<String, dynamic> map) {
    final stairUpRaw = map['stairUp'] as Map<String, dynamic>?;
    final stairDownRaw = map['stairDown'] as Map<String, dynamic>?;
    final tilesRaw = map['tiles'] as List<dynamic>? ?? [];

    final tiles = tilesRaw
        .map((row) {
          final rowList = row as List<dynamic>;
          return rowList
              .map((cell) => Tile.fromMap(cell as Map<String, dynamic>))
              .toList();
        })
        .toList();

    return Floor(
      level: map['level'] as int? ?? 0,
      name: map['name'] as String? ?? 'Floor',
      width: map['width'] as int? ?? 11,
      height: map['height'] as int? ?? 11,
      tiles: tiles.cast<List<Tile>>(),
      stairUp: stairUpRaw != null
          ? Point(stairUpRaw['x'] as int, stairUpRaw['y'] as int)
          : null,
      stairDown: stairDownRaw != null
          ? Point(stairDownRaw['x'] as int, stairDownRaw['y'] as int)
          : null,
      requiredKey: map['requiredKey'] as String?,
      bossDefeated: map['bossDefeated'] as bool? ?? false,
    );
  }

  // ── equality / hashCode ──────────────────────────────────────────────

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is Floor && level == other.level;

  @override
  int get hashCode => level.hashCode;

  @override
  String toString() => 'Floor($level: $name)';
}

// ─────────────────────────────────────────────────────────────────────────────
// Battle result
// ─────────────────────────────────────────────────────────────────────────────

/// Who won a battle.
enum BattleWinner {
  player,
  monster,
}

/// Outcome of a single battle encounter.
class BattleResult {
  final BattleWinner winner;
  final int playerDamageTaken;
  final int monsterDamageDealt;
  final int rounds;
  final int goldEarned;
  final int expEarned;

  BattleResult({
    required this.winner,
    required this.playerDamageTaken,
    required this.monsterDamageDealt,
    required this.rounds,
    required this.goldEarned,
    required this.expEarned,
  });

  /// Convenience: did the player win?
  bool get isPlayerWin => winner == BattleWinner.player;

  /// Convenience: did the player die?
  bool get isPlayerDead => winner == BattleWinner.monster;

  // ── serialisation ────────────────────────────────────────────────────

  Map<String, dynamic> toMap() => {
        'winner': winner.name,
        'playerDamageTaken': playerDamageTaken,
        'monsterDamageDealt': monsterDamageDealt,
        'rounds': rounds,
        'goldEarned': goldEarned,
        'expEarned': expEarned,
      };

  factory BattleResult.fromMap(Map<String, dynamic> map) {
    final raw = map['winner'] as String? ?? 'monster';
    final winner = raw == 'player' ? BattleWinner.player : BattleWinner.monster;
    return BattleResult(
      winner: winner,
      playerDamageTaken: map['playerDamageTaken'] as int? ?? 0,
      monsterDamageDealt: map['monsterDamageDealt'] as int? ?? 0,
      rounds: map['rounds'] as int? ?? 0,
      goldEarned: map['goldEarned'] as int? ?? 0,
      expEarned: map['expEarned'] as int? ?? 0,
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// GameState
// ─────────────────────────────────────────────────────────────────────────────

/// Runtime game state that is shared across the UI and gameplay layers.
class GameState {
  /// The player character.
  PlayerState player;

  /// All loaded floors.
  List<Floor> floors;

  /// Currently active floor index.
  int currentFloorIndex;

  /// Whether a battle is currently in progress.
  bool isBattleActive;

  /// Whether the shop UI is open.
  bool isInShop;

  /// Whether a dialogue is currently displayed.
  bool isInDialogue;

  /// Current dialogue text.
  String dialogueText;

  /// Result of the last battle (null when no battle occurred).
  BattleResult? battleResult;

  /// NPC messages that have been triggered.
  List<String> npcMessages;

  /// Whether the game is over (player died with no revive).
  bool isGameOver;

  /// Whether the game is paused.
  bool isPaused;

  GameState({
    this.player = PlayerState(),
    this.floors = const [],
    this.currentFloorIndex = 0,
    this.isBattleActive = false,
    this.isInShop = false,
    this.isInDialogue = false,
    this.dialogueText = '',
    this.battleResult,
    this.npcMessages = const [],
    this.isGameOver = false,
    this.isPaused = false,
  });

  // ── state setters ────────────────────────────────────────────────────

  void setCurrentFloor(int index) {
    currentFloorIndex = index;
  }

  void setBattleActive(bool active) {
    isBattleActive = active;
  }

  void setShopActive(bool active) {
    isInShop = active;
  }

  void setDialogueActive(bool active, String text) {
    isInDialogue = active;
    dialogueText = text;
  }

  void setBattleResult(BattleResult? result) {
    battleResult = result;
  }

  void setGameOver(bool over) {
    isGameOver = over;
  }

  void setPaused(bool paused) {
    isPaused = paused;
  }

  void addNpcMessage(String message) {
    npcMessages.add(message);
  }

  void clearNpcMessages() {
    npcMessages.clear();
  }

  // ── serialisation ────────────────────────────────────────────────────

  Map<String, dynamic> toMap() => {
        'currentFloorIndex': currentFloorIndex,
        'isBattleActive': isBattleActive,
        'isInShop': isInShop,
        'isInDialogue': isInDialogue,
        'isGameOver': isGameOver,
        'isPaused': isPaused,
        'dialogueText': dialogueText,
        'floors': floors.map((f) => f.toMap()).toList(),
        'npcMessages': npcMessages,
      };

  factory GameState.fromMap(Map<String, dynamic> map) {
    final floorsRaw = map['floors'] as List<dynamic>? ?? [];
    final floors = floorsRaw
        .map((f) => Floor.fromMap(f as Map<String, dynamic>))
        .toList();
    final player = PlayerState.fromMap(
      Map<String, dynamic>.from(map['player'] as Map? ?? {}),
    );
    return GameState(
      player: player,
      floors: floors,
      currentFloorIndex: map['currentFloorIndex'] as int? ?? 0,
      isBattleActive: map['isBattleActive'] as bool? ?? false,
      isInShop: map['isInShop'] as bool? ?? false,
      isInDialogue: map['isInDialogue'] as bool? ?? false,
      dialogueText: map['dialogueText'] as String? ?? '',
      battleResult: map['battleResult'] != null
          ? BattleResult.fromMap(map['battleResult'] as Map<String, dynamic>)
          : null,
      npcMessages: (map['npcMessages'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          [],
      isGameOver: map['isGameOver'] as bool? ?? false,
      isPaused: map['isPaused'] as bool? ?? false,
    );
  }

  /// Shallow copy.
  GameState copy() {
    return GameState(
      player: player.copy(),
      floors: List.from(floors),
      currentFloorIndex: currentFloorIndex,
      isBattleActive: isBattleActive,
      isInShop: isInShop,
      isInDialogue: isInDialogue,
      dialogueText: dialogueText,
      battleResult: battleResult,
      npcMessages: List.from(npcMessages),
      isGameOver: isGameOver,
      isPaused: isPaused,
    );
  }

  /// Non-destructive update: returns a new [GameState] with the
  /// supplied fields replaced.  Omitted fields keep their current
  /// value.
  GameState copyWith({
    PlayerState? player,
    List<Floor>? floors,
    int? currentFloorIndex,
    bool? isBattleActive,
    bool? isInShop,
    bool? isInDialogue,
    String? dialogueText,
    BattleResult? battleResult,
    List<String>? npcMessages,
    bool? isGameOver,
    bool? isPaused,
  }) {
    return GameState(
      player: player ?? this.player,
      floors: floors ?? this.floors,
      currentFloorIndex: currentFloorIndex ?? this.currentFloorIndex,
      isBattleActive: isBattleActive ?? this.isBattleActive,
      isInShop: isInShop ?? this.isInShop,
      isInDialogue: isInDialogue ?? this.isInDialogue,
      dialogueText: dialogueText ?? this.dialogueText,
      battleResult: battleResult ?? this.battleResult,
      npcMessages: npcMessages ?? List.from(this.npcMessages),
      isGameOver: isGameOver ?? this.isGameOver,
      isPaused: isPaused ?? this.isPaused,
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SaveData
// ─────────────────────────────────────────────────────────────────────────────

/// Top-level save data envelope.
class SaveData {
  /// Schema version.
  final String version;

  /// Unix timestamp (milliseconds) when the save was created.
  final int timestamp;

  /// Game state at the time of saving.
  final GameState gameState;

  SaveData({
    this.version = '1.0.0',
    this.timestamp = 0,
    required this.gameState,
  }) : timestamp = timestamp == 0 ? DateTime.now().millisecondsSinceEpoch : timestamp;

  // ── serialisation ────────────────────────────────────────────────────

  Map<String, dynamic> toMap() => {
        'version': version,
        'timestamp': timestamp,
        'gameState': gameState.toMap(),
      };

  factory SaveData.fromMap(Map<String, dynamic> map) {
    return SaveData(
      version: map['version'] as String? ?? '1.0.0',
      timestamp: map['timestamp'] as int? ?? 0,
      gameState: GameState.fromMap(
        Map<String, dynamic>.from(map['gameState'] as Map? ?? {}),
      ),
    );
  }
}
