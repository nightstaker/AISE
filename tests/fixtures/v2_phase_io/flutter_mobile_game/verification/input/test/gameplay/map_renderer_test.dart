import 'package:magic_tower/gameplay/map_renderer.dart';
import 'package:test/test.dart';

void main() {
  group('MapRenderer', () {
    late MapRenderer renderer;

    setUp(() {
      renderer = MapRenderer();
      renderer.initialize(
        tileSize: 48,
        mapWidth: 11,
        mapHeight: 11,
        screenOffsetX: 0,
        screenOffsetY: 0,
      );
    });

    group('initialization', () {
      test('isInitialized returns true', () {
        expect(renderer.isInitialized, isTrue);
      });

      test('tileSize is correct', () {
        expect(renderer.tileSize, equals(48));
      });

      test('mapWidth is correct', () {
        expect(renderer.mapWidth, equals(11));
      });

      test('mapHeight is correct', () {
        expect(renderer.mapHeight, equals(11));
      });

      test('screenOffsetX is correct', () {
        expect(renderer.screenOffsetX, equals(0));
      });

      test('screenOffsetY is correct', () {
        expect(renderer.screenOffsetY, equals(0));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.tileSize, throwsStateError);
      });
    });

    group('getTilePixelPosition', () {
      test('returns correct pixel position for (0,0)', () {
        final pos = renderer.getTilePixelPosition(0, 0);
        expect(pos['x'], equals(0));
        expect(pos['y'], equals(0));
      });

      test('returns correct pixel position for (1,1)', () {
        final pos = renderer.getTilePixelPosition(1, 1);
        expect(pos['x'], equals(48));
        expect(pos['y'], equals(48));
      });

      test('returns correct pixel position for (2,3)', () {
        final pos = renderer.getTilePixelPosition(2, 3);
        expect(pos['x'], equals(96));
        expect(pos['y'], equals(144));
      });

      test('returns correct with offset', () {
        renderer.screenOffsetX = 10;
        renderer.screenOffsetY = 20;
        final pos = renderer.getTilePixelPosition(1, 1);
        expect(pos['x'], equals(58));
        expect(pos['y'], equals(68));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.getTilePixelPosition(0, 0), throwsStateError);
      });
    });

    group('getTileColor', () {
      test('returns wall color', () {
        expect(renderer.getTileColor(TileType.wall), equals(ColorCode.wall));
      });

      test('returns floor color', () {
        expect(renderer.getTileColor(TileType.floor), equals(ColorCode.floor));
      });

      test('returns stairsUp color', () {
        expect(renderer.getTileColor(TileType.stairsUp),
            equals(ColorCode.stairsUp));
      });

      test('returns stairsDown color', () {
        expect(renderer.getTileColor(TileType.stairsDown),
            equals(ColorCode.stairsDown));
      });

      test('returns door color', () {
        expect(renderer.getTileColor(TileType.door), equals(ColorCode.door));
      });

      test('returns monster color', () {
        expect(renderer.getTileColor(TileType.monster),
            equals(ColorCode.monster));
      });

      test('returns item color', () {
        expect(renderer.getTileColor(TileType.item), equals(ColorCode.item));
      });

      test('returns npc color', () {
        expect(renderer.getTileColor(TileType.npc), equals(ColorCode.npc));
      });

      test('returns shop color', () {
        expect(renderer.getTileColor(TileType.shop), equals(ColorCode.shop));
      });

      test('returns boss color', () {
        expect(renderer.getTileColor(TileType.boss), equals(ColorCode.boss));
      });

      test('returns hiddenRoom color', () {
        expect(renderer.getTileColor(TileType.hiddenRoom),
            equals(ColorCode.hiddenRoom));
      });

      test('returns lockedDoor color', () {
        expect(renderer.getTileColor(TileType.lockedDoor),
            equals(ColorCode.lockedDoor));
      });

      test('returns empty color', () {
        expect(renderer.getTileColor(TileType.empty), equals(ColorCode.empty));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.getTileColor(TileType.wall), throwsStateError);
      });
    });

    group('getDoorColor', () {
      test('returns red color for red door', () {
        expect(renderer.getDoorColor(DoorColor.red), equals(ColorCode.redDoor));
      });

      test('returns blue color for blue door', () {
        expect(renderer.getDoorColor(DoorColor.blue),
            equals(ColorCode.blueDoor));
      });

      test('returns yellow color for yellow door', () {
        expect(renderer.getDoorColor(DoorColor.yellow),
            equals(ColorCode.yellowDoor));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.getDoorColor(DoorColor.red), throwsStateError);
      });
    });

    group('setTileColor', () {
      test('sets custom color for tile type', () {
        renderer.setTileColor(TileType.wall, ColorCode.customWall);
        expect(renderer.getTileColor(TileType.wall), equals(ColorCode.customWall));
      });

      test('resets color', () {
        renderer.setTileColor(TileType.wall, ColorCode.customWall);
        renderer.resetTileColor(TileType.wall);
        expect(renderer.getTileColor(TileType.wall), equals(ColorCode.wall));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(
            () => fresh.setTileColor(TileType.wall, ColorCode.customWall),
            throwsStateError);
      });
    });

    group('getScreenPosition', () {
      test('returns screen position with offset', () {
        renderer.screenOffsetX = 100;
        renderer.screenOffsetY = 50;
        final pos = renderer.getScreenPosition(2, 3);
        expect(pos['x'], equals(196));
        expect(pos['y'], equals(194));
      });

      test('returns screen position without offset', () {
        final pos = renderer.getScreenPosition(0, 0);
        expect(pos['x'], equals(0));
        expect(pos['y'], equals(0));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.getScreenPosition(0, 0), throwsStateError);
      });
    });

    group('getPixelBounds', () {
      test('returns correct bounds for tile', () {
        final bounds = renderer.getPixelBounds(1, 1);
        expect(bounds['left'], equals(48));
        expect(bounds['top'], equals(48));
        expect(bounds['right'], equals(96));
        expect(bounds['bottom'], equals(96));
      });

      test('returns correct bounds for corner tile', () {
        final bounds = renderer.getPixelBounds(0, 0);
        expect(bounds['left'], equals(0));
        expect(bounds['top'], equals(0));
        expect(bounds['right'], equals(48));
        expect(bounds['bottom'], equals(48));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.getPixelBounds(0, 0), throwsStateError);
      });
    });

    group('setScreenOffset', () {
      test('sets screen offset', () {
        renderer.setScreenOffset(100, 50);
        expect(renderer.screenOffsetX, equals(100));
        expect(renderer.screenOffsetY, equals(50));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.setScreenOffset(100, 50), throwsStateError);
      });
    });

    group('toJson / fromJson', () {
      test('serializes and deserializes correctly', () {
        renderer.setTileColor(TileType.wall, ColorCode.customWall);
        renderer.setScreenOffset(100, 50);

        final json = renderer.toJson();
        final restored = MapRenderer.fromJson(json);

        expect(restored.tileSize, equals(48));
        expect(restored.mapWidth, equals(11));
        expect(restored.mapHeight, equals(11));
        expect(restored.screenOffsetX, equals(100));
        expect(restored.screenOffsetY, equals(50));
        expect(restored.getTileColor(TileType.wall),
            equals(ColorCode.customWall));
      });

      test('throws when not initialized', () {
        final fresh = MapRenderer();
        expect(() => fresh.screenOffsetX = 10, throwsStateError);
      });
    });
  });
}
