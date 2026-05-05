/// In-App Purchase (IAP) Provider — Mock Implementation
///
/// Provides a mock in-app purchase flow using the `in_app_purchase`
/// package interface.  In production this would connect to Google Play
/// Billing / Apple StoreKit; here all purchases succeed immediately
/// without blocking the UI thread.
///
/// Contract:
/// - `iapProductId` → "magic_tower_gold_pack" (gold coin bundle)
/// - `purchaseGold(amount)` → adds [amount] gold to player
/// - `isAvailable` → always true (mock)
/// - `purchaseHistory` → list of mock purchases

import 'package:flutter/foundation.dart';

/// Represents a completed IAP transaction.
class IapTransaction {
  IapTransaction({
    required this.productId,
    required this.amount,
    required this.timestamp,
    this.transactionId = 'mock_tx_001',
  });

  /// The product identifier (e.g. "magic_tower_gold_pack").
  final String productId;

  /// Amount of gold purchased.
  final int amount;

  /// ISO-8601 timestamp of the purchase.
  final DateTime timestamp;

  /// Mock transaction ID (in production this comes from the store).
  final String transactionId;

  Map<String, dynamic> toJson() => {
        'productId': productId,
        'amount': amount,
        'timestamp': timestamp.toIso8601String(),
        'transactionId': transactionId,
      };
}

/// Mock IAP provider — simulates the `in_app_purchase` API surface
/// without requiring a real store connection.
class IapProvider {
  IapProvider();

  bool _initialized = false;

  /// Whether the IAP system is available (always true in mock mode).
  bool get isAvailable => _initialized;

  /// Whether the user is subscribed to IAP (always true in mock mode).
  bool get isSubscribed => _initialized;

  /// List of available products.
  List<IapProduct> get availableProducts => _products;

  /// Purchase history.
  final List<IapTransaction> _transactions = [];
  List<IapTransaction> get purchaseHistory => List.unmodifiable(_transactions);

  /// Callback fired when a purchase completes.
  ValueChanged<IapTransaction>? onPurchaseComplete;

  /// Callback fired when a purchase fails (never fires in mock mode).
  ValueChanged<String>? onPurchaseFailed;

  // ------------------------------------------------------------------
  // Product definitions
  // ------------------------------------------------------------------

  static const List<IapProduct> _products = [
    IapProduct(
      productId: 'magic_tower_gold_100',
      title: '100 Gold',
      description: '购买 100 金币',
      priceCny: '¥1.00',
      goldAmount: 100,
    ),
    IapProduct(
      productId: 'magic_tower_gold_500',
      title: '500 Gold',
      description: '购买 500 金币',
      priceCny: '¥5.00',
      goldAmount: 500,
    ),
    IapProduct(
      productId: 'magic_tower_gold_2000',
      title: '2000 Gold',
      description: '购买 2000 金币',
      priceCny: '¥18.00',
      goldAmount: 2000,
    ),
  ];

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------

  /// Initialize the IAP system.
  ///
  /// In mock mode this always succeeds.
  Future<bool> initialize() async {
    _initialized = true;
    debugPrint('[IAP] Mock IAP system initialized');
    return true;
  }

  /// Dispose the IAP system.
  void dispose() {
    _initialized = false;
    _transactions.clear();
  }

  // ------------------------------------------------------------------
  // Purchase API
  // ------------------------------------------------------------------

  /// Purchase a product by [productId].
  ///
  /// In mock mode the purchase always succeeds and returns gold
  /// immediately.
  Future<IapTransaction?> purchase(String productId) async {
    if (!_initialized) {
      debugPrint('[IAP] Not initialized');
      onPurchaseFailed?.call('not_initialized');
      return null;
    }

    final product = availableProducts.firstWhere(
      (p) => p.productId == productId,
      orElse: () => throw ArgumentError('Unknown product: $productId'),
    );

    final transaction = IapTransaction(
      productId: productId,
      amount: product.goldAmount,
      timestamp: DateTime.now(),
    );

    _transactions.add(transaction);
    debugPrint('[IAP] Purchase successful: $productId (${product.goldAmount} gold)');
    onPurchaseComplete?.call(transaction);

    return transaction;
  }

  /// Purchase a specific amount of gold.
  ///
  /// This is the "Buy Gold" button action in the game.
  Future<IapTransaction?> purchaseGold(int amount) async {
    return purchase('magic_tower_gold_${amount}');
  }

  /// Restore previous purchases (mock always returns empty).
  Future<List<IapTransaction>> restorePurchases() async {
    debugPrint('[IAP] Restore purchases (mock: no-op)');
    return List.from(_transactions);
  }

  // ------------------------------------------------------------------
  // Query API
  // ------------------------------------------------------------------

  /// Get product details by ID.
  IapProduct? getProduct(String productId) {
    try {
      return availableProducts.firstWhere((p) => p.productId == productId);
    } catch (_) {
      return null;
    }
  }

  /// Check if a product is consumable (always true for mock).
  bool isConsumable(String productId) {
    return availableProducts.any((p) => p.productId == productId);
  }
}

/// Represents an in-app purchase product.
class IapProduct {
  IapProduct({
    required this.productId,
    required this.title,
    required this.description,
    required this.priceCny,
    required this.goldAmount,
  });

  /// Unique product identifier.
  final String productId;

  /// Display title.
  final String title;

  /// Product description.
  final String description;

  /// Price in CNY.
  final String priceCny;

  /// Amount of gold the player receives.
  final int goldAmount;
}
