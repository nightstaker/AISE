/// HUD (Heads-Up Display) — game overlay showing player stats and floor info.
///
/// Responsibilities:
/// - Display HP, ATK, DEF, Gold, EXP, Level.
/// - Show current floor number.
/// - Show action buttons (up/down/left/right/attack/items).

import 'package:flutter/material.dart';

import '../data/models.dart';

/// HUD widget that overlays player stats on the game screen.
class HUDUI extends StatefulWidget {
  /// Current player state to display.
  final PlayerState player;

  /// Current floor number (1-based).
  final int floorNumber;

  /// Whether to show the action buttons row.
  final bool showActionButtons;

  /// Callback when the player presses the "up" movement button.
  final VoidCallback onUp;

  /// Callback when the player presses the "down" movement button.
  final VoidCallback onDown;

  /// Callback when the player presses the "left" movement button.
  final VoidCallback onLeft;

  /// Callback when the player presses the "right" movement button.
  final VoidCallback onRight;

  /// Callback when the player presses the "attack" button.
  final VoidCallback onAttack;

  /// Callback when the player opens the inventory.
  final VoidCallback onInventory;

  /// Callback when the player opens the IAP (in-app purchase) store.
  final VoidCallback onIapPurchase;

  const HUDUI({
    super.key,
    this.player = _defaultPlayer,
    this.floorNumber = 1,
    this.showActionButtons = true,
    this.onUp = _noop,
    this.onDown = _noop,
    this.onLeft = _noop,
    this.onRight = _noop,
    this.onAttack = _noop,
    this.onInventory = _noop,
    this.onIapPurchase = _noop,
  });

  static PlayerState get _defaultPlayer => PlayerState(
    hp: 0, atk: 0, def: 0, gold: 0, exp: 0, level: 1,
  );
  static void _noop() {}

  @override
  State<HUDUI> createState() => _HUDUIState();

  /// Initialize this HUD. Called by the app's lifecycle init.
  void initialize() {
    // HUD is stateless in terms of initialization.
  }

  bool get isInitialized => true;
}

class _HUDUIState extends State<HUDUI> {
  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Top bar: stats
        _buildStatsBar(context),
        // Middle: game area placeholder
        Expanded(child: _buildGameArea(context)),
        // Bottom: action buttons
        if (widget.showActionButtons) _buildActionButtons(context),
      ],
    );
  }

  Widget _buildStatsBar(BuildContext context) {
    final p = widget.player;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      color: Colors.black87,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          _statChip(context, 'HP', '${p.hp}', Colors.red),
          _statChip(context, 'ATK', '${p.atk}', Colors.orange),
          _statChip(context, 'DEF', '${p.def}', Colors.blue),
          _statChip(context, 'Gold', '${p.gold}', Colors.amber),
          _statChip(context, 'Lv', '${p.level}', Colors.purple),
        ],
      ),
    );
  }

  Widget _statChip(
    BuildContext context,
    String label,
    String value,
    Color color,
  ) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.3),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        '$label: $value',
        style: const TextStyle(color: Colors.white, fontSize: 12),
      ),
    );
  }

  Widget _buildGameArea(BuildContext context) {
    return Container(
      color: Colors.grey[800],
      child: Center(
        child: Text(
          'Floor ${widget.floorNumber}',
          style: const TextStyle(color: Colors.white70, fontSize: 18),
        ),
      ),
    );
  }

  Widget _buildActionButtons(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(8),
      color: Colors.black87,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          _actionButton(context, Icons.arrow_upward, 'Up', widget.onUp),
          _actionButton(context, Icons.arrow_downward, 'Down', widget.onDown),
          _actionButton(context, Icons.arrow_back, 'Left', widget.onLeft),
          _actionButton(context, Icons.arrow_forward, 'Right', widget.onRight),
          _actionButton(context, Icons.swords, 'Attack', widget.onAttack),
          _actionButton(context, Icons.inventory, 'Items', widget.onInventory),
          _actionButton(context, Icons.shopping_cart, 'Shop', widget.onIapPurchase),
        ],
      ),
    );
  }

  Widget _actionButton(
    BuildContext context,
    IconData icon,
    String label,
    VoidCallback onPressed,
  ) {
    return Column(
      children: [
        ElevatedButton(
          onPressed: onPressed,
          style: ElevatedButton.styleFrom(
            backgroundColor: Colors.amber[700],
            padding: const EdgeInsets.all(12),
            minimumSize: const Size(48, 48),
          ),
          child: Icon(icon, color: Colors.white),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: const TextStyle(color: Colors.white70, fontSize: 10),
        ),
      ],
    );
  }
}
