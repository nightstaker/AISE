/// Shop screen — merchandise purchase interface.
///
/// Responsibilities:
/// - Display available items for sale.
/// - Handle gold deduction on purchase.
/// - Update inventory after purchase.

import 'package:flutter/material.dart';

import '../data/models.dart';
import '../gameplay/shop_engine.dart';

/// Shop screen widget — shows purchasable items.
class ShopScreen extends StatefulWidget {
  /// Available items in the shop.
  final List<ShopItem> shopItems;

  /// Player's current gold.
  final int playerGold;

  /// Callback when the player purchases an item.
  final ValueChanged<String> onPurchase;

  /// Callback to close the shop.
  final VoidCallback onClose;

  const ShopScreen({
    super.key,
    this.shopItems = const [],
    this.playerGold = 0,
    this.onPurchase = _noopStr,
    this.onClose = _noop,
  });

  static void _noop() {}
  static void _noopStr(String s) {}

  @override
  State<ShopScreen> createState() => _ShopScreenState();

  /// Initialize this screen. Called by the app's lifecycle init.
  void initialize() {
    // ShopScreen is stateful; initialization handled in initState.
  }

  bool get isInitialized => true;
}

class _ShopScreenState extends State<ShopScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.brown[900],
      appBar: AppBar(
        title: const Text('商店'),
        backgroundColor: Colors.brown[700],
        actions: [
          TextButton(
            onPressed: widget.onClose,
            child: const Text(
              '关闭',
              style: TextStyle(color: Colors.white),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          // Player gold display
          Container(
            color: Colors.black87,
            padding: const EdgeInsets.all(12),
            child: Text(
              '金币: ${widget.playerGold}',
              style: const TextStyle(
                color: Colors.amber,
                fontSize: 20,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          // Item list
          Expanded(
            child: ListView.builder(
              itemCount: widget.shopItems.length,
              itemBuilder: (context, index) {
                final item = widget.shopItems[index];
                return _buildShopItem(context, item);
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildShopItem(BuildContext context, ShopItem item) {
    final canAfford = widget.playerGold >= item.price;
    return ListTile(
      leading: Container(
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          color: item.color ?? Colors.grey,
          borderRadius: BorderRadius.circular(8),
        ),
      ),
      title: Text(item.name),
      subtitle: Text('价格: ${item.price} 金币'),
      trailing: ElevatedButton(
        onPressed: canAfford ? () => widget.onPurchase(item.name) : null,
        style: ElevatedButton.styleFrom(
          backgroundColor: canAfford ? Colors.amber[700] : Colors.grey,
        ),
        child: Text('购买'),
      ),
    );
  }
}
