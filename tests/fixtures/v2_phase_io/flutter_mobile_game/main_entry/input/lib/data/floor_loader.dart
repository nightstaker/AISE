/// floor_*.json parsing + map data-driven floor loading.
///
/// Parses JSON-encoded floor definitions into [Floor] objects.
/// Supports loading from raw [Map<String, dynamic>] payloads
/// (suitable for both asset files and in-memory mock data).

import 'package:magic_tower/data/models.dart';

/// Parses a JSON-like map into a [Floor] with monster and NPC data.
///
/// [raw] is a map parsed from `floor_*.json`.  Required keys:
///   - `level` (int) — floor number
///   - `name` (String) — display name
///   - `tiles` (List<List<Map>> — 2-D tile grid
///
/// Optional keys:
///   - `width`, `height` — tile grid dimensions (defaults 11)
///   - `stairUp`, `stairDown` — `{"x": int, "y": int}` or null
///   - `requiredKey` — key type string, or null
///   - `monsters` — `{"x,y": MonsterDef}` map
///   - `items` — `{"x,y": ItemDef}` map
///   - `npcs` — `{"x,y": NpcDef}` map
///   - `bossDefeated` — bool
///   - `unlockCondition` — arbitrary metadata (ignored by loader)
class FloorLoader {
  /// Load a single floor from a JSON-like map.
  ///
  /// Returns `null` when the map is missing a required `level` key
  /// or when the `tiles` array is empty.
  Floor? loadFloor(Map<String, dynamic> raw) {
    if (raw['level'] == null) return null;

    final level = raw['level'] as int;
    final name = raw['name'] as String? ?? 'Floor $level';
    final width = raw['width'] as int? ?? 11;
    final height = raw['height'] as int? ?? 11;

    // Parse stair positions
    Point? stairUp;
    final stairUpRaw = raw['stairUp'] as Map<String, dynamic>?;
    if (stairUpRaw != null) {
      stairUp = Point(
        stairUpRaw['x'] as int? ?? 0,
        stairUpRaw['y'] as int? ?? 0,
      );
    }

    Point? stairDown;
    final stairDownRaw = raw['stairDown'] as Map<String, dynamic>?;
    if (stairDownRaw != null) {
      stairDown = Point(
        stairDownRaw['x'] as int? ?? 0,
        stairDownRaw['y'] as int? ?? 0,
      );
    }

    // Parse required key
    ItemType? requiredKey;
    final requiredKeyStr = raw['requiredKey'] as String?;
    if (requiredKeyStr != null) {
      requiredKey = ItemType.fromName(requiredKeyStr);
    }

    // Parse boss defeated flag
    final bossDefeated = raw['bossDefeated'] as bool? ?? false;

    // Parse tiles
    final tilesRaw = raw['tiles'] as List<dynamic>?;
    if (tilesRaw == null || tilesRaw.isEmpty) {
      return null;
    }

    final tiles = <List<Tile>>[];
    for (final row in tilesRaw) {
      final rowList = row as List<dynamic>;
      final tileRow = rowList
          .map((cell) {
            if (cell is Map<String, dynamic>) {
              return Tile.fromMap(cell);
            }
            return Tile(type: TileType.floor);
          })
          .toList();
      tiles.add(tileRow);
    }

    return Floor(
      level: level,
      name: name,
      width: width,
      height: height,
      tiles: tiles,
      stairUp: stairUp,
      stairDown: stairDown,
      requiredKey: requiredKey,
      bossDefeated: bossDefeated,
    );
  }

  /// Load a floor by integer identifier using the built-in mock data.
  ///
  /// In production this would read from `assets/floor_${floorId}.json`.
  Floor? loadFloorById(int floorId) {
    final json = _resolveFloorJson(floorId);
    if (json == null) return null;
    return loadFloor(json);
  }

  /// Load multiple floors by their integer identifiers.
  List<Floor> loadFloorsByIds(List<int> floorIds) {
    final floors = <Floor>[];
    for (final id in floorIds) {
      final floor = loadFloorById(id);
      if (floor != null) floors.add(floor);
    }
    return floors;
  }

  /// Batch load from raw JSON maps.
  ///
  /// Skips entries that are `null` or fail to parse.
  List<Floor> loadBatch(List<Map<String, dynamic>?> sources) {
    final floors = <Floor>[];
    for (final src in sources) {
      if (src != null) {
        final floor = loadFloor(src);
        if (floor != null) floors.add(floor);
      }
    }
    return floors;
  }

  /// Register a custom JSON provider for a floor id.
  ///
  /// [provider] receives a floor id and returns a raw JSON map, or `null`
  /// when the floor does not exist.  This lets tests inject mock data.
  void registerProvider(FloorJsonProvider provider) {
    _customProvider = provider;
  }

  // ── internal helpers ────────────────────────────────────────────────

  /// Function type for external JSON providers.
  Map<String, dynamic>? Function(int floorId) _customProvider = _defaultProvider;

  Map<String, dynamic>? _resolveFloorJson(int floorId) {
    return _customProvider(floorId);
  }

  static Map<String, dynamic>? _defaultProvider(int floorId) {
    if (floorId == 1) return _floor1Data();
    if (floorId == 2) return _floor2Data();
    if (floorId == 3) return _floor3Data();
    return null;
  }

  // ── built-in mock floor data ────────────────────────────────────────

  static Map<String, dynamic> _floor1Data() {
    return {
      'level': 1,
      'name': 'First Floor',
      'width': 11,
      'height': 11,
      'tiles': _generateBorderFloor(),
      'stairUp': {'x': 5, 'y': 5},
      'stairDown': null,
      'monsters': {
        '5,3': {
          'type': 'slime',
          'name': 'Slime',
          'hp': 50,
          'atk': 5,
          'def': 2,
          'gold': 10,
          'exp': 5,
          'symbol': 's',
        },
      },
      'items': {
        '3,5': {
          'type': 'redPotion',
          'name': 'Red Potion',
          'hpRestore': 50,
          'quantity': 1,
        },
      },
      'npcs': {
        '8,5': {
          'id': 'elder',
          'name': 'Village Elder',
          'dialogue': 'Welcome, brave hero. Climb the tower and defeat the monsters!',
        },
      },
    };
  }

  static Map<String, dynamic> _floor2Data() {
    return {
      'level': 2,
      'name': 'Second Floor',
      'width': 11,
      'height': 11,
      'tiles': _generateCorridorFloor(),
      'stairUp': {'x': 5, 'y': 10},
      'stairDown': {'x': 5, 'y': 0},
      'monsters': {
        '5,5': {
          'type': 'goblin',
          'name': 'Goblin',
          'hp': 80,
          'atk': 8,
          'def': 4,
          'gold': 20,
          'exp': 10,
          'symbol': 'g',
        },
      },
      'items': {
        '2,2': {
          'type': 'redGem',
          'name': 'Red Gem',
          'atkBoost': 2,
          'quantity': 1,
        },
      },
    };
  }

  static Map<String, dynamic> _floor3Data() {
    return {
      'level': 3,
      'name': 'Boss Floor',
      'width': 11,
      'height': 11,
      'tiles': _generateArenaFloor(),
      'stairUp': {'x': 5, 'y': 10},
      'stairDown': {'x': 5, 'y': 0},
      'requiredKey': 'redKey',
      'monsters': {
        '5,5': {
          'type': 'dragon',
          'name': 'Dragon Boss',
          'hp': 500,
          'atk': 30,
          'def': 15,
          'gold': 500,
          'exp': 200,
          'symbol': 'D',
          'isBoss': true,
        },
      },
    };
  }

  /// 11x11 grid: wall border, floor inside.
  static List<List<Map<String, dynamic>>> _generateBorderFloor() {
    return List.generate(11, (y) {
      return List.generate(11, (x) {
        final isBorder = x == 0 || x == 10 || y == 0 || y == 10;
        return {'type': isBorder ? 'wall' : 'floor'};
      });
    });
  }

  /// 11x11 grid: wall border, corridor in the middle.
  static List<List<Map<String, dynamic>>> _generateCorridorFloor() {
    return List.generate(11, (y) {
      return List.generate(11, (x) {
        final isBorder = x == 0 || x == 10 || y == 0 || y == 10;
        final isWall = x == 5 && y > 2 && y < 8;
        return {'type': isBorder || isWall ? 'wall' : 'floor'};
      });
    });
  }

  /// 11x11 grid: wall border, open arena with a central pillar.
  static List<List<Map<String, dynamic>>> _generateArenaFloor() {
    return List.generate(11, (y) {
      return List.generate(11, (x) {
        final isBorder = x == 0 || x == 10 || y == 0 || y == 10;
        final isPillar = x == 5 && y >= 4 && y <= 6;
        return {'type': isBorder || isPillar ? 'wall' : 'floor'};
      });
    });
  }
}
