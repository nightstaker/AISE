/// 楼层管理器：11×11 地图管理 + 楼层切换逻辑
///
/// Manages the floor grid, entities on each floor (monsters, items, NPCs,
/// shops, bosses, doors, stairs), and floor transition logic.

class FloorMgr {
  FloorMgr();

  bool _initialized = false;
  int _currentFloor = 1;
  int _playerX = 5;
  int _playerY = 10;
  int _mapSize = 11;
  int _minFloor = 1;
  int _maxFloor = 10;

  // === entity maps ===
  final Map<String, bool> _walls = {};
  final Map<String, String> _monsters = {};
  final Map<String, DoorColor> _doors = {};
  final Map<String, String> _items = {};
  final Map<String, String> _npcs = {};
  final Map<String, bool> _shops = {};
  final Map<String, String> _bosses = {};
  final Map<String, bool> _stairsUp = {};
  final Map<String, bool> _stairsDown = {};

  int get currentFloor => _checkInit(_currentFloor);
  int get playerX => _checkInit(_playerX);
  int get playerY => _checkInit(_playerY);
  int get mapSize => _checkInit(_mapSize);
  bool get isInitialized => _initialized;

  void initialize({
    int mapSize = 11,
    int minFloor = 1,
    int maxFloor = 10,
    int startFloor = 1,
    int startPosX = 5,
    int startPosY = 10,
  }) {
    _mapSize = mapSize;
    _minFloor = minFloor;
    _maxFloor = maxFloor;
    _currentFloor = startFloor;
    _playerX = startPosX;
    _playerY = startPosY;
    _initialized = true;
  }

  void setFloor(int floor) {
    _checkInit();
    _currentFloor = floor.clamp(_minFloor, _maxFloor);
  }

  bool goUpFloor() {
    _checkInit();
    if (_currentFloor < _maxFloor) {
      _currentFloor++;
      return true;
    }
    return false;
  }

  bool goDownFloor() {
    _checkInit();
    if (_currentFloor > _minFloor) {
      _currentFloor--;
      return true;
    }
    return false;
  }

  bool movePlayer(int dx, int dy) {
    _checkInit();
    final newX = _playerX + dx;
    final newY = _playerY + dy;

    // Check bounds
    if (newX < 0 || newX >= _mapSize || newY < 0 || newY >= _mapSize) return false;

    // Check walls
    if (_walls.containsKey('${newX},${newY}')) return false;

    // Check monsters
    if (_monsters.containsKey('${newX},${newY}')) return false;

    // Check doors
    final doorColor = _doors['$newX,$newY'];
    if (doorColor != null) return false;

    // Check if stairs
    if (hasStairsUp(newX, newY)) {
      _playerX = newX;
      _playerY = newY;
      goUpFloor();
      return true;
    }

    if (hasStairsDown(newX, newY)) {
      _playerX = newX;
      _playerY = newY;
      goDownFloor();
      return true;
    }

    // Move player
    _playerX = newX;
    _playerY = newY;
    return true;
  }

  // === Walls ===
  void setWallAt(int x, int y) {
    _walls['$x,$y'] = true;
  }

  void removeWallAt(int x, int y) {
    _walls.remove('$x,$y');
  }

  bool isWall(int x, int y) {
    return _walls.containsKey('$x,$y');
  }

  // === Stairs ===
  void setStairsUpAt(int x, int y) {
    _stairsUp['$x,$y'] = true;
  }

  void removeStairsUpAt(int x, int y) {
    _stairsUp.remove('$x,$y');
  }

  bool hasStairsUp(int x, int y) {
    return _stairsUp.containsKey('$x,$y');
  }

  Map<String, int>? getStairsUpPosition() {
    if (_stairsUp.isEmpty) return null;
    final key = _stairsUp.keys.first;
    final parts = key.split(',');
    return {'x': int.parse(parts[0]), 'y': int.parse(parts[1])};
  }

  void setStairsDownAt(int x, int y) {
    _stairsDown['$x,$y'] = true;
  }

  void removeStairsDownAt(int x, int y) {
    _stairsDown.remove('$x,$y');
  }

  bool hasStairsDown(int x, int y) {
    return _stairsDown.containsKey('$x,$y');
  }

  Map<String, int>? getStairsDownPosition() {
    if (_stairsDown.isEmpty) return null;
    final key = _stairsDown.keys.first;
    final parts = key.split(',');
    return {'x': int.parse(parts[0]), 'y': int.parse(parts[1])};
  }

  // === Doors ===
  void setDoorColor(int x, int y, DoorColor color) {
    _doors['$x,$y'] = color;
  }

  void unlockDoor(int x, int y) {
    _doors.remove('$x,$y');
  }

  DoorColor? getDoorColor(int x, int y) {
    return _doors['$x,$y'];
  }

  bool hasDoor(int x, int y) {
    return _doors.containsKey('$x,$y');
  }

  // === Monsters ===
  void setMonsterAt(int x, int y, String monsterId) {
    _monsters['$x,$y'] = monsterId;
  }

  void removeMonster(int x, int y) {
    _monsters.remove('$x,$y');
  }

  String? getMonsterAt(int x, int y) {
    return _monsters['$x,$y'];
  }

  bool hasMonster(int x, int y) {
    return _monsters.containsKey('$x,$y');
  }

  // === Items ===
  void setItemAt(int x, int y, String itemId) {
    _items['$x,$y'] = itemId;
  }

  void removeItem(int x, int y) {
    _items.remove('$x,$y');
  }

  String? getItemAt(int x, int y) {
    return _items['$x,$y'];
  }

  bool hasItem(int x, int y) {
    return _items.containsKey('$x,$y');
  }

  // === NPCs ===
  void setNpcAt(int x, int y, String npcId) {
    _npcs['$x,$y'] = npcId;
  }

  void removeNpc(int x, int y) {
    _npcs.remove('$x,$y');
  }

  String? getNpcAt(int x, int y) {
    return _npcs['$x,$y'];
  }

  bool hasNpc(int x, int y) {
    return _npcs.containsKey('$x,$y');
  }

  // === Shops ===
  void setShopAt(int x, int y) {
    _shops['$x,$y'] = true;
  }

  void removeShop(int x, int y) {
    _shops.remove('$x,$y');
  }

  bool hasShop(int x, int y) {
    return _shops.containsKey('$x,$y');
  }

  // === Bosses ===
  void setBossAt(int x, int y, String bossId) {
    _bosses['$x,$y'] = bossId;
  }

  void removeBoss(int x, int y) {
    _bosses.remove('$x,$y');
  }

  String? getBossAt(int x, int y) {
    return _bosses['$x,$y'];
  }

  bool hasBoss(int x, int y) {
    return _bosses.containsKey('$x,$y');
  }

  // === Public read-only access for GameStateNotifier ===

  /// All monster positions keyed by "x,y" → monsterId.
  Map<String, String> get monsters => Map.unmodifiable(_monsters);

  /// All NPC positions keyed by "x,y" → npcId.
  Map<String, String> get npcs => Map.unmodifiable(_npcs);

  /// All item positions keyed by "x,y" → itemId.
  Map<String, String> get items => Map.unmodifiable(_items);

  // === Clear floor ===
  void clearFloor() {
    _monsters.clear();
    _items.clear();
    _npcs.clear();
    _shops.clear();
    _bosses.clear();
    _doors.clear();
    _stairsUp.clear();
    _stairsDown.clear();
  }

  // === Serialization ===
  Map<String, dynamic> toJson() {
    return {
      'floor': _currentFloor,
      'playerX': _playerX,
      'playerY': _playerY,
      'mapSize': _mapSize,
      'walls': _walls.keys.toList(),
      'stairsUp': _stairsUp.keys.toList(),
      'stairsDown': _stairsDown.keys.toList(),
      'monsters': _monsters.map((k, v) => MapEntry(k, v)),
      'items': _items.map((k, v) => MapEntry(k, v)),
      'npcs': _npcs.map((k, v) => MapEntry(k, v)),
      'shops': _shops.keys.toList(),
      'bosses': _bosses.map((k, v) => MapEntry(k, v)),
      'doors': _doors.map((k, v) => MapEntry(k, v.name)),
    };
  }

  factory FloorMgr.fromJson(Map<String, dynamic> json) {
    final mgr = FloorMgr();
    mgr._currentFloor = json['floor'] as int;
    mgr._playerX = json['playerX'] as int;
    mgr._playerY = json['playerY'] as int;
    mgr._mapSize = json['mapSize'] as int;
    mgr._minFloor = 1;
    mgr._maxFloor = 100;
    mgr._walls = Map.fromIterable(
      (json['walls'] as List<dynamic>).cast<String>(),
      key: (v) => v as String,
      value: (v) => true,
    );
    mgr._stairsUp = Map.fromIterable(
      (json['stairsUp'] as List<dynamic>).cast<String>(),
      key: (v) => v as String,
      value: (v) => true,
    );
    mgr._stairsDown = Map.fromIterable(
      (json['stairsDown'] as List<dynamic>).cast<String>(),
      key: (v) => v as String,
      value: (v) => true,
    );
    mgr._monsters = (json['monsters'] as Map<String, dynamic>).cast<String, String>();
    mgr._items = (json['items'] as Map<String, dynamic>).cast<String, String>();
    mgr._npcs = (json['npcs'] as Map<String, dynamic>).cast<String, String>();
    mgr._bosses = (json['bosses'] as Map<String, dynamic>).cast<String, String>();
    final doors = (json['doors'] as Map<String, dynamic>);
    mgr._doors = doors.map((k, v) => MapEntry(k, DoorColor.values.firstWhere(
      (e) => e.name == v,
      orElse: () => DoorColor.red,
    )));
    mgr._initialized = true;
    return mgr;
  }

  void _checkInit([dynamic returnValue]) {
    if (!_initialized) throw StateError('FloorMgr not initialized');
    return returnValue;
  }
}
