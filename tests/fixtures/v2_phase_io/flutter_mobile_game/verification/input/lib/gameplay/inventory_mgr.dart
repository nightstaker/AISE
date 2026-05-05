/// 道具拾取/使用：钥匙/血瓶/宝石
///
/// Manages the player's inventory including keys, potions, gems,
/// and other collectible items.

// ignore_for_file: public_member_api_docs

class InventoryMgr {
  InventoryMgr();

  bool _initialized = false;
  final Map<String, InventoryItem> _items = {};
  int _maxSlots = 10;

  int get count => _checkInit(_items.length);
  bool get isEmpty => _checkInit(_items.isEmpty);
  int get maxSlots => _checkInit(_maxSlots);
  bool get isInitialized => _initialized;

  void initialize({int maxSlots = 10}) {
    _maxSlots = maxSlots;
    _initialized = true;
  }

  void addItem(String id, String name, ItemType type, {
    int healAmount = 0,
    int atkBoost = 0,
    int defBoost = 0,
  }) {
    _checkInit();
    if (_items.length >= _maxSlots) {
      throw StateError('Inventory is full');
    }
    _items[id] = InventoryItem(
      id: id,
      name: name,
      type: type,
      healAmount: healAmount,
      atkBoost: atkBoost,
      defBoost: defBoost,
    );
  }

  bool removeItem(String id) {
    _checkInit();
    return _items.remove(id) != null;
  }

  bool hasItem(String id) {
    _checkInit();
    return _items.containsKey(id);
  }

  ItemType? getItemType(String id) {
    _checkInit();
    return _items[id]?.type;
  }

  int useItem(String id) {
    _checkInit();
    final item = _items[id];
    if (item == null) return 0;

    switch (item.type) {
      case ItemType.redPotion:
      case ItemType.bluePotion:
        final heal = item.healAmount;
        _items.remove(id);
        return heal;
      case ItemType.redGem:
        final boost = item.atkBoost;
        _items.remove(id);
        return boost;
      case ItemType.blueGem:
        final boost = item.defBoost;
        _items.remove(id);
        return boost;
      case ItemType.sword:
        final boost = item.atkBoost;
        _items.remove(id);
        return boost;
      case ItemType.armor:
        final boost = item.defBoost;
        _items.remove(id);
        return boost;
      case ItemType.yellowKey:
      case ItemType.blueKey:
      case ItemType.redKey:
        return 0;
    }
  }

  bool useKey(KeyColor color) {
    _checkInit();
    final id = '${color.name}Key';
    if (_items.containsKey(id)) {
      _items.remove(id);
      return true;
    }
    return false;
  }

  bool hasKey(KeyColor color) {
    _checkInit();
    final id = '${color.name}Key';
    return _items.containsKey(id);
  }

  void clearInventory() {
    _checkInit();
    _items.clear();
  }

  Map<String, dynamic> toJson() {
    _checkInit();
    return {
      'items': _items.values.map((item) => item.toJson()).toList(),
      'maxSlots': _maxSlots,
    };
  }

  factory InventoryMgr.fromJson(Map<String, dynamic> json) {
    final mgr = InventoryMgr();
    mgr._maxSlots = json['maxSlots'] as int;
    mgr._items = (json['items'] as List<dynamic>)
        .map((e) => InventoryItem.fromJson(e as Map<String, dynamic>))
        .fold<Map<String, InventoryItem>>(
          {},
          (map, item) => map..[item.id] = item,
        );
    mgr._initialized = true;
    return mgr;
  }

  void _checkInit([dynamic returnValue]) {
    if (!_initialized) throw StateError('InventoryMgr not initialized');
    return returnValue;
  }
}

/// Represents an item in the inventory.
class InventoryItem {
  InventoryItem({
    required this.id,
    required this.name,
    required this.type,
    this.healAmount = 0,
    this.atkBoost = 0,
    this.defBoost = 0,
  });

  final String id;
  final String name;
  final ItemType type;
  final int healAmount;
  final int atkBoost;
  final int defBoost;

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'type': type.name,
      'healAmount': healAmount,
      'atkBoost': atkBoost,
      'defBoost': defBoost,
    };
  }

  factory InventoryItem.fromJson(Map<String, dynamic> json) {
    return InventoryItem(
      id: json['id'] as String,
      name: json['name'] as String,
      type: _parseItemType(json['type'] as String),
      healAmount: json['healAmount'] as int? ?? 0,
      atkBoost: json['atkBoost'] as int? ?? 0,
      defBoost: json['defBoost'] as int? ?? 0,
    );
  }

  static ItemType _parseItemType(String name) {
    return ItemType.values.firstWhere(
      (e) => e.name == name,
      orElse: () => ItemType.redPotion,
    );
  }
}

/// Item type covering all collectible items.
enum ItemType {
  yellowKey,
  blueKey,
  redKey,
  redPotion,
  bluePotion,
  redGem,
  blueGem,
  sword,
  armor,
}

/// Key color for keys.
enum KeyColor {
  yellow,
  blue,
  red,
}
