/// Tile rendering logic + color placeholders
///
/// Manages tile-to-pixel position mapping, color assignments for
/// different tile types, and screen offset calculations.

import 'package:magic_tower/data/models.dart';

// ignore_for_file: public_member_api_docs

class MapRenderer {
  MapRenderer();

  bool _initialized = false;
  int _tileSize = 48;
  int _mapWidth = 11;
  int _mapHeight = 11;
  int _screenOffsetX = 0;
  int _screenOffsetY = 0;
  final Map<TileType, int> _customColors = {};

  int get tileSize => _checkInit(_tileSize);
  int get mapWidth => _checkInit(_mapWidth);
  int get mapHeight => _checkInit(_mapHeight);
  int get screenOffsetX => _checkInit(_screenOffsetX);
  int get screenOffsetY => _checkInit(_screenOffsetY);
  bool get isInitialized => _initialized;

  set screenOffsetX(int value) {
    _checkInit();
    _screenOffsetX = value;
  }

  set screenOffsetY(int value) {
    _checkInit();
    _screenOffsetY = value;
  }

  void initialize({
    int tileSize = 48,
    int mapWidth = 11,
    int mapHeight = 11,
    int screenOffsetX = 0,
    int screenOffsetY = 0,
  }) {
    _tileSize = tileSize;
    _mapWidth = mapWidth;
    _mapHeight = mapHeight;
    _screenOffsetX = screenOffsetX;
    _screenOffsetY = screenOffsetY;
    _initialized = true;
  }

  Map<String, int> getTilePixelPosition(int tileX, int tileY) {
    _checkInit();
    return {
      'x': (tileX * _tileSize + _screenOffsetX),
      'y': (tileY * _tileSize + _screenOffsetY),
    };
  }

  int getTileColor(TileType type) {
    _checkInit();
    if (_customColors.containsKey(type)) return _customColors[type]!;

    switch (type) {
      case TileType.wall:
        return ColorCode.wall;
      case TileType.floor:
        return ColorCode.floor;
      case TileType.stairsUp:
        return ColorCode.stairsUp;
      case TileType.stairsDown:
        return ColorCode.stairsDown;
      case TileType.door:
        return ColorCode.door;
      case TileType.monster:
        return ColorCode.monster;
      case TileType.item:
        return ColorCode.item;
      case TileType.npc:
        return ColorCode.npc;
      case TileType.shop:
        return ColorCode.shop;
      case TileType.boss:
        return ColorCode.boss;
      case TileType.hiddenRoom:
        return ColorCode.hiddenRoom;
      case TileType.lockedDoor:
        return ColorCode.lockedDoor;
      case TileType.empty:
        return ColorCode.empty;
    }
  }

  int getDoorColor(DoorColor color) {
    _checkInit();
    switch (color) {
      case DoorColor.red:
        return ColorCode.redDoor;
      case DoorColor.blue:
        return ColorCode.blueDoor;
      case DoorColor.yellow:
        return ColorCode.yellowDoor;
    }
  }

  void setTileColor(TileType type, int color) {
    _checkInit();
    _customColors[type] = color;
  }

  void resetTileColor(TileType type) {
    _checkInit();
    _customColors.remove(type);
  }

  Map<String, int> getScreenPosition(int tileX, int tileY) {
    _checkInit();
    return {
      'x': (tileX * _tileSize + _screenOffsetX),
      'y': (tileY * _tileSize + _screenOffsetY),
    };
  }

  Map<String, int> getPixelBounds(int tileX, int tileY) {
    _checkInit();
    return {
      'left': tileX * _tileSize + _screenOffsetX,
      'top': tileY * _tileSize + _screenOffsetY,
      'right': (tileX + 1) * _tileSize + _screenOffsetX,
      'bottom': (tileY + 1) * _tileSize + _screenOffsetY,
    };
  }

  void setScreenOffset(int x, int y) {
    _checkInit();
    _screenOffsetX = x;
    _screenOffsetY = y;
  }

  Map<String, dynamic> toJson() {
    return {
      'tileSize': _tileSize,
      'mapWidth': _mapWidth,
      'mapHeight': _mapHeight,
      'screenOffsetX': _screenOffsetX,
      'screenOffsetY': _screenOffsetY,
      'customColors': _customColors.map((k, v) => MapEntry(k.name, v)),
    };
  }

  factory MapRenderer.fromJson(Map<String, dynamic> json) {
    final renderer = MapRenderer();
    renderer._tileSize = json['tileSize'] as int;
    renderer._mapWidth = json['mapWidth'] as int;
    renderer._mapHeight = json['mapHeight'] as int;
    renderer._screenOffsetX = json['screenOffsetX'] as int;
    renderer._screenOffsetY = json['screenOffsetY'] as int;
    renderer._customColors = (json['customColors'] as Map<String, dynamic>)
        .map((k, v) => MapEntry(
              TileType.values.firstWhere(
                (e) => e.name == k,
                orElse: () => TileType.floor,
              ),
              v as int,
            ));
    renderer._initialized = true;
    return renderer;
  }

  void _checkInit([dynamic returnValue]) {
    if (!_initialized) throw StateError('MapRenderer not initialized');
    return returnValue;
  }
}
