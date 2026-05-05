/// 商品列表管理 + 购买流程
///
/// Manages the shop's inventory, item listings, and purchase flow.
/// Uses the shared [ItemType] from [package:magic_tower/data/models.dart].

// ignore_for_file: public_member_api_docs

import 'package:magic_tower/data/models.dart';

/// Result of a purchase attempt.
class PurchaseResult {
  PurchaseResult({
    required this.success,
    required this.message,
    this.item,
    this.goldRemaining = 0,
    this.itemAdded = false,
    this.healAmount = 0,
    this.atkBoost = 0,
    this.defBoost = 0,
  });

  /// Whether the purchase succeeded.
  final bool success;

  /// Human-readable message describing the result.
  final String message;

  /// The item that was purchased (null if failed).
  final ShopItem? item;

  /// Player's gold remaining after the transaction.
  final int goldRemaining;

  /// Whether the item was added to player inventory.
  final bool itemAdded;

  /// HP heal amount from this item.
  final int healAmount;

  /// ATK boost from this item.
  final int atkBoost;

  /// DEF boost from this item.
  final int defBoost;
}

/// A single item available for purchase in the shop.
class ShopItem {
  ShopItem({
    required this.id,
    required this.name,
    required this.type,
    required this.price,
    this.healAmount = 0,
    this.atkBoost = 0,
    this.defBoost = 0,
    this.color,
  });

  /// Unique identifier for this shop item.
  final String id;

  /// Display name for this shop item.
  final String name;

  /// The [ItemType] of this shop item.
  final ItemType type;

  /// Price in gold coins.
  final int price;

  /// HP heal amount (for potions).
  final int healAmount;

  /// ATK boost amount (for gems / swords).
  final int atkBoost;

  /// DEF boost amount (for gems / armor).
  final int defBoost;

  /// Display color for the shop item icon (UI hint).
  final Color? color;

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'type': type.name,
      'price': price,
      'healAmount': healAmount,
      'atkBoost': atkBoost,
      'defBoost': defBoost,
    };
  }

  factory ShopItem.fromJson(Map<String, dynamic> json) {
    return ShopItem(
      id: json['id'] as String,
      name: json['name'] as String,
      type: _parseItemType(json['type'] as String),
      price: json['price'] as int,
      healAmount: json['healAmount'] as int? ?? 0,
      atkBoost: json['atkBoost'] as int? ?? 0,
      defBoost: json['defBoost'] as int? ?? 0,
    );
  }

  static ItemType _parseItemType(String name) {
    return ItemType.values.firstWhere(
      (e) => e.name == name,
      orElse: () => ItemType.none,
    );
  }
}

/// Shop engine — manages the shop's inventory and purchase flow.
///
/// Responsibilities:
/// - Maintain a catalog of [ShopItem] objects.
/// - Validate and process purchases against player gold.
/// - Return structured [PurchaseResult] for UI consumption.
class ShopEngine {
  ShopEngine();

  bool _initialized = false;
  final Map<String, ShopItem> _items = {};
  int _maxSlots = 10;

  int get itemCount => _checkInit(_items.length);
  int get maxSlots => _checkInit(_maxSlots);
  bool get isEmpty => _checkInit(_items.isEmpty);
  bool get isInitialized => _initialized;

  /// Initialize the shop engine.
  ///
  /// Must be called before any shop operations.
  void initialize({required int maxSlots}) {
    _maxSlots = maxSlots;
    _initialized = true;
  }

  // ── Catalog management ────────────────────────────────────────────────

  /// Add an item to the shop catalog.
  void addItem({
    required String id,
    required String name,
    required ItemType type,
    required int price,
    int healAmount = 0,
    int atkBoost = 0,
    int defBoost = 0,
  }) {
    _checkInit();
    if (_items.length >= _maxSlots) {
      throw StateError('Shop is full');
    }
    _items[id] = ShopItem(
      id: id,
      name: name,
      type: type,
      price: price,
      healAmount: healAmount,
      atkBoost: atkBoost,
      defBoost: defBoost,
    );
  }

  /// Remove an item from the shop catalog. Returns true if the item existed.
  bool removeItem(String id) {
    _checkInit();
    return _items.remove(id) != null;
  }

  /// Get an item from the catalog by id, or null.
  ShopItem? getItem(String id) {
    _checkInit();
    return _items[id];
  }

  /// Check if an item exists in the catalog.
  bool hasItem(String id) {
    _checkInit();
    return _items.containsKey(id);
  }

  /// Return all shop items as JSON-serializable maps.
  List<Map<String, dynamic>> getShopItems() {
    _checkInit();
    return _items.values.map((item) => item.toJson()).toList();
  }

  /// Clear the entire shop catalog.
  void clearShop() {
    _checkInit();
    _items.clear();
  }

  // ── Purchase flow ──────────────────────────────────────────────────────

  /// Purchase an item from the shop.
  ///
  /// [playerGold] is the player's current gold amount.
  /// [playerAtk] and [playerDef] are used to determine which item
  /// effects are applicable (e.g. swords only add ATK, armor only adds DEF).
  ///
  /// Returns a [PurchaseResult] describing the outcome.
  PurchaseResult purchase({
    required String itemId,
    required int playerGold,
    required int playerAtk,
    required int playerDef,
  }) {
    _checkInit();

    final item = _items[itemId];
    if (item == null) {
      return PurchaseResult(
        success: false,
        message: 'Item not found in shop',
        goldRemaining: playerGold,
      );
    }

    if (playerGold < item.price) {
      return PurchaseResult(
        success: false,
        message: 'Not enough gold',
        goldRemaining: playerGold,
      );
    }

    if (item.price <= 0) {
      return PurchaseResult(
        success: false,
        message: 'Invalid item price',
        goldRemaining: playerGold,
      );
    }

    final newGold = playerGold - item.price;
    final healAmount = item.healAmount;
    final atkBoost = item.atkBoost;
    final defBoost = item.defBoost;

    return PurchaseResult(
      success: true,
      message: 'Purchase successful',
      item: item,
      goldRemaining: newGold,
      itemAdded: true,
      healAmount: healAmount,
      atkBoost: atkBoost,
      defBoost: defBoost,
    );
  }

  /// Purchase multiple items in sequence.
  ///
  /// [purchaseRequests] is a list of item ids to buy.
  /// [playerGold] is deducted cumulatively.
  /// Returns a list of [PurchaseResult] for each request.
  List<PurchaseResult> purchaseMany({
    required List<String> itemIds,
    required int playerGold,
    required int playerAtk,
    required int playerDef,
  }) {
    _checkInit();
    final results = <PurchaseResult>[];
    var remainingGold = playerGold;

    for (final itemId in itemIds) {
      final result = purchase(
        itemId: itemId,
        playerGold: remainingGold,
        playerAtk: playerAtk,
        playerDef: playerDef,
      );
      results.add(result);
      if (result.success) {
        remainingGold = result.goldRemaining;
      }
    }

    return results;
  }

  // ── Serialization ──────────────────────────────────────────────────────

  Map<String, dynamic> toJson() {
    return {
      'items': _items.values.map((item) => item.toJson()).toList(),
      'maxSlots': _maxSlots,
    };
  }

  factory ShopEngine.fromJson(Map<String, dynamic> json) {
    final shop = ShopEngine();
    shop._maxSlots = json['maxSlots'] as int;
    shop._items = (json['items'] as List<dynamic>)
        .map((e) => ShopItem.fromJson(e as Map<String, dynamic>))
        .fold<Map<String, ShopItem>>(
          {},
          (map, item) => map..[item.id] = item,
        );
    shop._initialized = true;
    return shop;
  }

  // ── Internal ───────────────────────────────────────────────────────────

  void _checkInit([dynamic returnValue]) {
    if (!_initialized) throw StateError('ShopEngine not initialized');
    return returnValue;
  }
}
