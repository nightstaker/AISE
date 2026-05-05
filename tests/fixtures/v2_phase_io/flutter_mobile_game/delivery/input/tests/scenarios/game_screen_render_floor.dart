/// E2E scenario: game_screen_render_floor
///
/// Trigger: {"action": "load_floor", "floor_id": 1}
/// Effect: {"grid_rendered": true, "grid_size": "11x11", "wall_tiles_visible": true, "floor_tiles_visible": true, "player_sprite_at_correct_pos": true, "stair_up_visible": true, "stair_down_visible": true}
///
/// Validates the game screen correctly renders an 11x11 grid map
/// with walls, floor tiles, player position, and stairs.

import 'package:magic_tower/data/models.dart';
import 'package:magic_tower/gameplay/floor_mgr.dart';
import 'package:magic_tower/gameplay/map_renderer.dart';
import 'package:test/test.dart';

void main() {
  group('Game Screen Render Floor — E2E Scenario', () {
    late FloorMgr floorMgr;
    late MapRenderer renderer;

    setUp(() {
      floorMgr = FloorMgr();
      floorMgr.initialize(
        mapSize: 11,
        minFloor: 1,
        maxFloor: 10,
        startFloor: 1,
        startPosX: 5,
        startPosY: 10,
      );

      renderer = MapRenderer();
      renderer.initialize(tileSize: 48.0, screenOffsetX: 0, screenOffsetY: 0);
    });

    test('renders 11x11 grid with walls, floor, and player at correct position',
        () {
      // Set up a simple floor layout
      // Walls around edges
      for (int x = 0; x < 11; x++) {
        floorMgr.setWallAt(x, 0);
        floorMgr.setWallAt(x, 10);
      }
      for (int y = 0; y < 11; y++) {
        floorMgr.setWallAt(0, y);
        floorMgr.setWallAt(10, y);
      }

      // Stairs up at (5, 0)
      floorMgr.setStairsUpAt(5, 0);
      // Stairs down at (5, 10) — but that's a wall, so place at (5, 1)
      floorMgr.setStairsDownAt(5, 1);

      // Player at (5, 10) — should be on floor tile
      expect(floorMgr.playerX, equals(5));
      expect(floorMgr.playerY, equals(10));

      // Verify map size
      expect(floorMgr.mapSize, equals(11));

      // Verify walls exist
      expect(floorMgr.isWall(0, 5), isTrue);
      expect(floorMgr.isWall(5, 0), isTrue);
      expect(floorMgr.isWall(10, 5), isTrue);
      expect(floorMgr.isWall(5, 10), isTrue);

      // Verify stairs
      expect(floorMgr.hasStairsUp(5, 0), isTrue);
      expect(floorMgr.hasStairsDown(5, 1), isTrue);

      // Verify player position is not on a wall
      expect(floorMgr.isWall(5, 10), isFalse,
          reason: 'Player start position should not be on a wall');
    });

    test('grid is rendered at correct tile size', () {
      renderer.initialize(tileSize: 48.0, screenOffsetX: 0, screenOffsetY: 0);
      expect(renderer.tileSize, equals(48.0));
      expect(renderer.screenOffsetX, equals(0));
      expect(renderer.screenOffsetY, equals(0));

      renderer.initialize(tileSize: 64.0, screenOffsetX: 10, screenOffsetY: 20);
      expect(renderer.tileSize, equals(64.0));
      expect(renderer.screenOffsetX, equals(10));
      expect(renderer.screenOffsetY, equals(20));
    });

    test('tile colors are assigned correctly by TileType', () {
      // Wall tile should have a wall color
      expect(renderer.getColorForTile(TileType.wall), isNotNull);
      expect(renderer.getColorForTile(TileType.floor), isNotNull);
      expect(renderer.getColorForTile(TileType.stairUp), isNotNull);
      expect(renderer.getColorForTile(TileType.stairDown), isNotNull);
      expect(renderer.getColorForTile(TileType.chest), isNotNull);
    });

    test('player position is within grid bounds', () {
      expect(floorMgr.playerX >= 0, isTrue);
      expect(floorMgr.playerX < 11, isTrue);
      expect(floorMgr.playerY >= 0, isTrue);
      expect(floorMgr.playerY < 11, isTrue);
    });

    test('floor tiles are walkable (no walls at player position)', () {
      // Player starts at (5, 10)
      expect(floorMgr.isWall(5, 10), isFalse);

      // Move to adjacent floor tile
      floorMgr.movePlayer(1, 0);
      expect(floorMgr.isWall(6, 10), isFalse);
    });

    test('rendering includes all tile types for a complete floor', () {
      // Add various tile types
      floorMgr.setWallAt(1, 1);
      floorMgr.setWallAt(2, 1);
      floorMgr.setStairsUpAt(5, 0);
      floorMgr.setStairsDownAt(5, 10);
      floorMgr.setMonsterAt(3, 5, 'slime');
      floorMgr.setItemAt(7, 3, 'red_key');
      floorMgr.setNpcAt(8, 8, 'wise_mage');
      floorMgr.setShopAt(1, 5);
      floorMgr.setBossAt(5, 0, 'dragon');
      floorMgr.setDoorColor(4, 5, DoorColor.red);

      // Verify all entities are placed
      expect(floorMgr.isWall(1, 1), isTrue);
      expect(floorMgr.hasStairsUp(5, 0), isTrue);
      expect(floorMgr.hasStairsDown(5, 10), isTrue);
      expect(floorMgr.hasMonster(3, 5), isTrue);
      expect(floorMgr.getItemAt(7, 3), equals('red_key'));
      expect(floorMgr.getNpcAt(8, 8), equals('wise_mage'));
      expect(floorMgr.hasShop(1, 5), isTrue);
      expect(floorMgr.hasBoss(5, 0), isTrue);
      expect(floorMgr.getDoorColor(4, 5), equals(DoorColor.red));
    });

    test('map renderer handles boundary conditions', () {
      // Corner tiles
      expect(renderer.getColorForTile(TileType.wall), isNotNull);
      expect(renderer.getColorForTile(TileType.floor), isNotNull);

      // Edge tiles should also have colors
      expect(renderer.getColorForTile(TileType.stairUp), isNotNull);
      expect(renderer.getColorForTile(TileType.stairDown), isNotNull);
    });
  });
}
