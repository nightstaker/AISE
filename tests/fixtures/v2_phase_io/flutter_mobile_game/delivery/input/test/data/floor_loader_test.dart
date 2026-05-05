/// Tests for [FloorLoader].
///
/// Covers: loadFloor, loadFloorById, loadFloorsByIds, loadBatch,
/// registerProvider, and various edge cases.

import 'package:magic_tower/data/floor_loader.dart';
import 'package:magic_tower/data/models.dart';
import 'package:test/test.dart';

void main() {
  group('FloorLoader', () {
    late FloorLoader loader;

    setUp(() {
      loader = FloorLoader();
    });

    // ── loadFloor ───────────────────────────────────────────────────────

    group('loadFloor', () {
      test('parses a valid floor map', () {
        final raw = {
          'level': 5,
          'name': 'Test Floor',
          'width': 11,
          'height': 11,
          'tiles': [
            [
              {'type': 'wall'},
              {'type': 'floor'},
            ],
            [
              {'type': 'floor'},
              {'type': 'floor'},
            ],
          ],
          'stairUp': {'x': 1, 'y': 0},
          'stairDown': null,
          'monsters': {},
          'items': {},
        };

        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
        expect(floor!.level, 5);
        expect(floor.name, 'Test Floor');
        expect(floor.width, 11);
        expect(floor.height, 11);
        expect(floor.stairUp, Point(1, 0));
        expect(floor.stairDown, isNull);
        expect(floor.tiles.length, 2);
        expect(floor.tiles[0].length, 2);
        expect(floor.tiles[0][0].type, TileType.wall);
        expect(floor.tiles[0][1].type, TileType.floor);
      });

      test('returns null when level key is missing', () {
        final raw = {
          'name': 'No Level',
          'tiles': [],
        };
        expect(loader.loadFloor(raw), isNull);
      });

      test('returns null when tiles is null', () {
        final raw = {
          'level': 1,
          'name': 'No Tiles',
          'tiles': null,
        };
        expect(loader.loadFloor(raw), isNull);
      });

      test('returns null when tiles is empty', () {
        final raw = {
          'level': 1,
          'name': 'Empty Tiles',
          'tiles': [],
        };
        expect(loader.loadFloor(raw), isNull);
      });

      test('uses defaults for missing optional fields', () {
        final raw = {
          'level': 2,
          'name': 'Minimal',
          'tiles': [[{'type': 'floor'}]],
        };

        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
        expect(floor!.width, 11);
        expect(floor.height, 11);
        expect(floor.stairUp, isNull);
        expect(floor.stairDown, isNull);
        expect(floor.requiredKey, isNull);
        expect(floor.bossDefeated, isFalse);
      });

      test('parses stairUp and stairDown positions', () {
        final raw = {
          'level': 3,
          'name': 'Stairs',
          'tiles': [[{'type': 'floor'}]],
          'stairUp': {'x': 3, 'y': 4},
          'stairDown': {'x': 7, 'y': 8},
        };

        final floor = loader.loadFloor(raw);
        expect(floor!.stairUp, Point(3, 4));
        expect(floor.stairDown, Point(7, 8));
      });

      test('parses requiredKey from string', () {
        final raw = {
          'level': 4,
          'name': 'Locked',
          'tiles': [[{'type': 'floor'}]],
          'requiredKey': 'redKey',
        };

        final floor = loader.loadFloor(raw);
        expect(floor!.requiredKey, ItemType.redKey);
      });

      test('parses bossDefeated flag', () {
        final raw = {
          'level': 5,
          'name': 'Boss Floor',
          'tiles': [[{'type': 'floor'}]],
          'bossDefeated': true,
        };

        final floor = loader.loadFloor(raw);
        expect(floor!.bossDefeated, isTrue);
      });

      test('handles unknown tile types gracefully', () {
        final raw = {
          'level': 6,
          'name': 'Unknown Tile',
          'tiles': [[{'type': 'unknownType'}]],
        };

        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
        // Unknown tile type falls back to floor
        expect(floor!.tiles[0][0].type, TileType.floor);
      });

      test('handles non-map cell entries gracefully', () {
        final raw = {
          'level': 7,
          'name': 'Bad Cell',
          'tiles': [[null, {'type': 'floor'}]],
        };

        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
        expect(floor!.tiles[0][0].type, TileType.floor);
        expect(floor.tiles[0][1].type, TileType.floor);
      });
    });

    // ── loadFloorById ───────────────────────────────────────────────────

    group('loadFloorById', () {
      test('loads floor 1 with default provider', () {
        final floor = loader.loadFloorById(1);
        expect(floor, isNotNull);
        expect(floor!.level, 1);
        expect(floor.name, 'First Floor');
        expect(floor.width, 11);
        expect(floor.height, 11);
      });

      test('loads floor 2 with default provider', () {
        final floor = loader.loadFloorById(2);
        expect(floor, isNotNull);
        expect(floor!.level, 2);
        expect(floor.name, 'Second Floor');
      });

      test('loads floor 3 with default provider', () {
        final floor = loader.loadFloorById(3);
        expect(floor, isNotNull);
        expect(floor!.level, 3);
        expect(floor.name, 'Boss Floor');
        expect(floor.requiredKey, ItemType.redKey);
      });

      test('returns null for non-existent floor', () {
        expect(loader.loadFloorById(999), isNull);
      });

      test('returns null for negative floor id', () {
        expect(loader.loadFloorById(-1), isNull);
      });
    });

    // ── loadFloorsByIds ─────────────────────────────────────────────────

    group('loadFloorsByIds', () {
      test('loads multiple existing floors', () {
        final floors = loader.loadFloorsByIds([1, 2, 3]);
        expect(floors.length, 3);
        expect(floors[0].level, 1);
        expect(floors[1].level, 2);
        expect(floors[2].level, 3);
      });

      test('skips non-existent floors', () {
        final floors = loader.loadFloorsByIds([1, 999, 2]);
        expect(floors.length, 2);
        expect(floors[0].level, 1);
        expect(floors[1].level, 2);
      });

      test('returns empty list for all non-existent floors', () {
        final floors = loader.loadFloorsByIds([998, 999]);
        expect(floors, isEmpty);
      });

      test('returns empty list for empty input', () {
        final floors = loader.loadFloorsByIds([]);
        expect(floors, isEmpty);
      });
    });

    // ── loadBatch ────────────────────────────────────────────────────────

    group('loadBatch', () {
      test('loads valid maps, skips nulls', () {
        final sources = [
          {
            'level': 10,
            'name': 'Floor 10',
            'tiles': [[{'type': 'floor'}]],
          },
          null,
          {
            'level': 11,
            'name': 'Floor 11',
            'tiles': [[{'type': 'floor'}]],
          },
        ];

        final floors = loader.loadBatch(sources);
        expect(floors.length, 2);
        expect(floors[0].level, 10);
        expect(floors[1].level, 11);
      });

      test('skips invalid maps', () {
        final sources = [
          {
            'level': 20,
            'name': 'Valid',
            'tiles': [[{'type': 'floor'}]],
          },
          {'name': 'No Level'}, // missing level
          {'level': 21, 'tiles': null}, // null tiles
        ];

        final floors = loader.loadBatch(sources);
        expect(floors.length, 1);
        expect(floors[0].level, 20);
      });

      test('handles empty list', () {
        final floors = loader.loadBatch([]);
        expect(floors, isEmpty);
      });

      test('handles all null list', () {
        final floors = loader.loadBatch([null, null]);
        expect(floors, isEmpty);
      });
    });

    // ── registerProvider ────────────────────────────────────────────────

    group('registerProvider', () {
      test('uses custom provider after registration', () {
        loader.registerProvider((id) {
          if (id == 42) {
            return {
              'level': 42,
              'name': 'Custom Floor',
              'tiles': [[{'type': 'floor'}]],
            };
          }
          return null;
        });

        final floor = loader.loadFloorById(42);
        expect(floor, isNotNull);
        expect(floor!.level, 42);
        expect(floor.name, 'Custom Floor');
      });

      test('custom provider overrides default for existing floors', () {
        loader.registerProvider((id) {
          if (id == 1) {
            return {
              'level': 1,
              'name': 'Overridden Floor 1',
              'tiles': [[{'type': 'floor'}]],
            };
          }
          return null;
        });

        final floor = loader.loadFloorById(1);
        expect(floor, isNotNull);
        expect(floor!.name, 'Overridden Floor 1');
      });

      test('custom provider returns null for non-existent floors', () {
        loader.registerProvider((id) => null);

        expect(loader.loadFloorById(1), isNull);
        expect(loader.loadFloorById(999), isNull);
      });
    });

    // ── tile type parsing ───────────────────────────────────────────────

    group('tile type parsing', () {
      final validTypes = [
        ('wall', TileType.wall),
        ('floor', TileType.floor),
        ('doorYellow', TileType.doorYellow),
        ('doorBlue', TileType.doorBlue),
        ('doorRed', TileType.doorRed),
        ('stairUp', TileType.stairUp),
        ('stairDown', TileType.stairDown),
        ('playerStart', TileType.playerStart),
        ('chest', TileType.chest),
        ('keyYellow', TileType.keyYellow),
        ('keyBlue', TileType.keyBlue),
        ('keyRed', TileType.keyRed),
        ('potionRed', TileType.potionRed),
        ('potionBlue', TileType.potionBlue),
        ('gemRed', TileType.gemRed),
        ('gemBlue', TileType.gemBlue),
        ('gemYellow', TileType.gemYellow),
        ('npc', TileType.npc),
        ('shop', TileType.shop),
        ('boss', TileType.boss),
        ('hidden', TileType.hidden),
      ];

      for (final (str, expected) in validTypes) {
        test('parses "$str" to $expected', () {
          final raw = {
            'level': 1,
            'name': 'Test',
            'tiles': [[{'type': str}]],
          };
          final floor = loader.loadFloor(raw);
          expect(floor!.tiles[0][0].type, expected);
        });
      }
    });

    // ── walkable property ───────────────────────────────────────────────

    group('walkable property', () {
      test('floor tile is walkable by default', () {
        final raw = {
          'level': 1,
          'name': 'Test',
          'tiles': [[{'type': 'floor'}]],
        };
        final floor = loader.loadFloor(raw);
        expect(floor!.tiles[0][0].walkable, isTrue);
      });

      test('wall tile is not walkable', () {
        final raw = {
          'level': 1,
          'name': 'Test',
          'tiles': [[{'type': 'wall'}]],
        };
        final floor = loader.loadFloor(raw);
        expect(floor!.tiles[0][0].walkable, isFalse);
      });

      test('walkable can be explicitly set to false', () {
        final raw = {
          'level': 1,
          'name': 'Test',
          'tiles': [[{'type': 'floor', 'walkable': false}]],
        };
        final floor = loader.loadFloor(raw);
        expect(floor!.tiles[0][0].walkable, isFalse);
      });

      test('walkable can be explicitly set to true', () {
        final raw = {
          'level': 1,
          'name': 'Test',
          'tiles': [[{'type': 'wall', 'walkable': true}]],
        };
        final floor = loader.loadFloor(raw);
        expect(floor!.tiles[0][0].walkable, isTrue);
      });
    });

    // ── edge cases ──────────────────────────────────────────────────────

    group('edge cases', () {
      test('handles very large floor id', () {
        expect(loader.loadFloorById(99999), isNull);
      });

      test('handles floor with no monsters', () {
        final raw = {
          'level': 1,
          'name': 'Empty',
          'tiles': [[{'type': 'floor'}]],
        };
        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
      });

      test('handles floor with no items', () {
        final raw = {
          'level': 1,
          'name': 'No Items',
          'tiles': [[{'type': 'floor'}]],
        };
        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
      });

      test('handles floor with no npcs', () {
        final raw = {
          'level': 1,
          'name': 'No NPCs',
          'tiles': [[{'type': 'floor'}]],
        };
        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
      });

      test('handles floor with all optional fields present', () {
        final raw = {
          'level': 99,
          'name': 'Full Floor',
          'width': 15,
          'height': 15,
          'tiles': [[{'type': 'floor'}]],
          'stairUp': {'x': 1, 'y': 1},
          'stairDown': {'x': 2, 'y': 2},
          'requiredKey': 'yellowKey',
          'bossDefeated': true,
          'monsters': {},
          'items': {},
          'npcs': {},
          'unlockCondition': 'defeat_dragon',
        };

        final floor = loader.loadFloor(raw);
        expect(floor, isNotNull);
        expect(floor!.level, 99);
        expect(floor.name, 'Full Floor');
        expect(floor.width, 15);
        expect(floor.height, 15);
        expect(floor.stairUp, Point(1, 1));
        expect(floor.stairDown, Point(2, 2));
        expect(floor.requiredKey, ItemType.yellowKey);
        expect(floor.bossDefeated, isTrue);
      });
    });
  });
}
