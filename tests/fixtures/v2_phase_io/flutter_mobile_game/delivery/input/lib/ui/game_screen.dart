/// Game screen — main gameplay view with map rendering, player movement,
/// and event handling.
///
/// Responsibilities:
/// - Render the current floor map with tile-based rendering.
/// - Handle player movement on the 11×11 grid with collision detection.
/// - Trigger events: combat, item pickup, door opening, NPC dialogue.
/// - Manage an event queue for debounced UI updates.
/// - Coordinate with HUDUI, floor_mgr, inventory_mgr, map_renderer, etc.

import 'package:flutter/material.dart';

import '../data/models.dart';
import 'hud_ui.dart';

/// Game screen widget — the main gameplay view.
///
/// Renders the floor map, handles player movement, and dispatches
/// events (combat, pickup, dialogue, stairs) to the parent controller.
class GameScreen extends StatefulWidget {
  /// Current floor number (1-based).
  final int floorNumber;

  /// Current player state.
  final PlayerState player;

  /// Whether the player can move (false during combat/dialogue).
  final bool canMove;

  /// Map of the current floor — tile data keyed by position.
  final Map<String, Tile> floorMap;

  /// Tile size in logical pixels for map rendering.
  final double tileSize;

  /// Map screen offset X.
  final int screenOffsetX;

  /// Map screen offset Y.
  final int screenOffsetY;

  /// Whether to show the minimap overlay.
  final bool showMinimap;

  /// Callback when the player moves.
  final ValueChanged<Direction> onMove;

  /// Callback to trigger combat with a monster.
  final ValueChanged<int> onCombat;

  /// Callback to open a dialogue with an NPC.
  final ValueChanged<String> onDialogue;

  /// Callback to pick up an item.
  final ValueChanged<String> onPickup;

  /// Callback to open the shop.
  final VoidCallback onShop;

  /// Callback to go up stairs.
  final VoidCallback onUpStairs;

  /// Callback to go down stairs.
  final VoidCallback onDownStairs;

  /// Callback when a message should be displayed to the player.
  final ValueChanged<String> onShowMessage;

  /// Callback when the map needs to be invalidated (e.g. after item pickup).
  final VoidCallback onMapRefresh;

  /// Callback to open the IAP (in-app purchase) store.
  final VoidCallback onIapPurchase;

  const GameScreen({
    super.key,
    this.floorNumber = 1,
    this.player = _defaultPlayer,
    this.canMove = true,
    this.floorMap = const {},
    this.tileSize = 48.0,
    this.screenOffsetX = 0,
    this.screenOffsetY = 0,
    this.showMinimap = true,
    this.onMove = _noopDir,
    this.onCombat = _noopInt,
    this.onDialogue = _noopStr,
    this.onPickup = _noopStr,
    this.onShop = _noop,
    this.onUpStairs = _noop,
    this.onDownStairs = _noop,
    this.onShowMessage = _noopStr,
    this.onMapRefresh = _noop,
    this.onIapPurchase = _noop,
  });

  static PlayerState get _defaultPlayer => PlayerState(
    hp: 0, atk: 0, def: 0, gold: 0, exp: 0, level: 1,
  );
  static void _noop() {}
  static void _noopDir(Direction d) {}
  static void _noopInt(int i) {}
  static void _noopStr(String s) {}

  @override
  State<GameScreen> createState() => _GameScreenState();

  /// Initialize this screen. Called by the app's lifecycle init.
  void initialize() {
    // GameScreen is stateful; initialization handled in initState.
  }

  bool get isInitialized => true;
}

/// Direction of player movement.
enum Direction {
  /// Move up (decreasing Y).
  up,

  /// Move down (increasing Y).
  down,

  /// Move left (decreasing X).
  left,

  /// Move right (increasing X).
  right,
}

/// Event types that can be queued for debounced processing.
enum GameEvent {
  /// Player moved to a new tile.
  move,

  /// Player initiated combat.
  combat,

  /// Player talked to an NPC.
  dialogue,

  /// Player picked up an item.
  pickup,

  /// Player opened the shop.
  shop,

  /// Player went up stairs.
  upStairs,

  /// Player went down stairs.
  downStairs,
}

class _GameScreenState extends State<GameScreen> {
  /// Queue of pending events to process (debounced).
  final List<GameEvent> _eventQueue = [];

  /// Last known player X for collision tracking.
  int _lastPlayerX = 5;

  /// Last known player Y for collision tracking.
  int _lastPlayerY = 10;

  /// Whether the map has been rendered at least once.
  bool _mapRendered = false;

  /// Track which tile types have been rendered for self-check.
  final Set<TileType> _renderedTypes = {};

  @override
  void initState() {
    super.initState();
    _lastPlayerX = 5;
    _lastPlayerY = 10;
  }

  @override
  void didUpdateWidget(covariant GameScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    // Process any queued events when the widget updates.
    _processEventQueue();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Top bar: HUD with player stats
        HUDUI(
          player: widget.player,
          floorNumber: widget.floorNumber,
          showActionButtons: false,
          onUp: () => _handleMove(Direction.up),
          onDown: () => _handleMove(Direction.down),
          onLeft: () => _handleMove(Direction.left),
          onRight: () => _handleMove(Direction.right),
          onAttack: () => _handleAttack(),
          onInventory: () => _handleInventory(),
        ),
        // Middle: game map area
        Expanded(child: _buildMapArea(context)),
        // Bottom: action buttons
        _buildActionButtons(context),
      ],
    );
  }

  /// Build the main map rendering area.
  Widget _buildMapArea(BuildContext context) {
    final mapWidth = (widget.tileSize * 11).ceil();
    final mapHeight = (widget.tileSize * 11).ceil();

    return Stack(
      children: [
        // Main map
        Container(
          width: mapWidth.toDouble(),
          height: mapHeight.toDouble(),
          decoration: BoxDecoration(
            color: Colors.grey[850],
            border: Border.all(color: Colors.black, width: 2),
          ),
          child: _buildTiles(context, mapWidth, mapHeight),
        ),
        // Minimap overlay
        if (widget.showMinimap)
          Positioned(
            top: 8,
            right: 8,
            child: _buildMinimap(context),
          ),
        // Message overlay
        if (_hasPendingMessage)
          Positioned(
            bottom: 60,
            left: 0,
            right: 0,
            child: _buildMessageOverlay(),
          ),
      ],
    );
  }

  /// Build individual tiles for the map.
  Widget _buildTiles(BuildContext context, int mapWidth, int mapHeight) {
    final tiles = <Widget>[];

    for (int y = 0; y < 11; y++) {
      for (int x = 0; x < 11; x++) {
        final key = '$x,$y';
        final tile = widget.floorMap[key];
        final tileType = tile?.type ?? TileType.empty;
        _renderedTypes.add(tileType);

        Color tileColor;
        switch (tileType) {
          case TileType.wall:
            tileColor = Colors.grey[700]!;
          case TileType.floor:
            tileColor = Colors.grey[300]!;
          case TileType.stairsUp:
            tileColor = Colors.green[300]!;
          case TileType.stairsDown:
            tileColor = Colors.red[300]!;
          case TileType.door:
            tileColor = Colors.orange[300]!;
          case TileType.monster:
            tileColor = Colors.red[700]!;
          case TileType.item:
            tileColor = Colors.amber[300]!;
          case TileType.npc:
            tileColor = Colors.blue[300]!;
          case TileType.shop:
            tileColor = Colors.purple[300]!;
          case TileType.boss:
            tileColor = Colors.red[900]!;
          case TileType.hiddenRoom:
            tileColor = Colors.grey[500]!;
          case TileType.lockedDoor:
            tileColor = Colors.red[500]!;
          case TileType.empty:
            tileColor = Colors.black;
        }

        final pixelX = x * widget.tileSize + widget.screenOffsetX;
        final pixelY = y * widget.tileSize + widget.screenOffsetY;

        tiles.add(
          Positioned(
            left: pixelX.clamp(0, mapWidth - widget.tileSize.toInt()),
            top: pixelY.clamp(0, mapHeight - widget.tileSize.toInt()),
            child: Container(
              width: widget.tileSize,
              height: widget.tileSize,
              color: tileColor,
              child: Center(
                child: _tileIcon(tileType, x, y),
              ),
            ),
          ),
        );
      }
    }

    // Draw player marker
    final playerTile = widget.floorMap['${_lastPlayerX},$_lastPlayerY'];
    if (playerTile != null && playerTile.type == TileType.floor) {
      final px = _lastPlayerX * widget.tileSize + widget.screenOffsetX;
      final py = _lastPlayerY * widget.tileSize + widget.screenOffsetY;
      tiles.add(
        Positioned(
          left: px.clamp(0, mapWidth - widget.tileSize.toInt()),
          top: py.clamp(0, mapHeight - widget.tileSize.toInt()),
          child: Container(
            width: widget.tileSize,
            height: widget.tileSize,
            color: Colors.blue,
            child: const Icon(Icons.person, color: Colors.white, size: 24),
          ),
        ),
      );
    }

    _mapRendered = true;
    return Stack(children: tiles);
  }

  /// Icon overlay for specific tile types.
  Widget _tileIcon(TileType type, int x, int y) {
    switch (type) {
      case TileType.stairsUp:
        return const Icon(Icons.arrow_upward, color: Colors.white, size: 20);
      case TileType.stairsDown:
        return const Icon(Icons.arrow_downward, color: Colors.white, size: 20);
      case TileType.monster:
        return const Icon(Icons.sports_martial_arts, color: Colors.white, size: 20);
      case TileType.item:
        return const Icon(Icons.card_giftcard, color: Colors.white, size: 20);
      case TileType.npc:
        return const Icon(Icons.face, color: Colors.white, size: 20);
      case TileType.shop:
        return const Icon(Icons.store, color: Colors.white, size: 20);
      case TileType.boss:
        return const Icon(Icons.verified_user, color: Colors.white, size: 28);
      case TileType.hiddenRoom:
        return const Icon(Icons.visibility_off, color: Colors.white, size: 20);
      case TileType.wall:
        return const Icon(Icons.block, color: Colors.white54, size: 16);
      case TileType.door:
      case TileType.lockedDoor:
        return const Icon(Icons.lock, color: Colors.white, size: 20);
      default:
        return const SizedBox.shrink();
    }
  }

  /// Build a small minimap showing the current floor layout.
  Widget _buildMinimap(BuildContext context) {
    return Container(
      width: 120,
      height: 120,
      decoration: BoxDecoration(
        color: Colors.black54,
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: Colors.white, width: 1),
      ),
      child: GridView.builder(
        shrinkWrap: true,
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: 11,
        ),
        itemCount: 121,
        itemBuilder: (_, index) {
          final x = index % 11;
          final y = index ~/ 11;
          final key = '$x,$y';
          final tile = widget.floorMap[key];
          final type = tile?.type ?? TileType.empty;

          Color color;
          switch (type) {
            case TileType.wall:
              color = Colors.grey[700]!;
            case TileType.floor:
              color = Colors.grey[300]!;
            case TileType.stairsUp:
              color = Colors.green[300]!;
            case TileType.stairsDown:
              color = Colors.red[300]!;
            case TileType.monster:
              color = Colors.red[700]!;
            case TileType.item:
              color = Colors.amber[300]!;
            case TileType.npc:
              color = Colors.blue[300]!;
            case TileType.shop:
              color = Colors.purple[300]!;
            case TileType.boss:
              color = Colors.red[900]!;
            case TileType.hiddenRoom:
              color = Colors.grey[500]!;
            default:
              color = Colors.black;
          }

          return Container(color: color);
        },
      ),
    );
  }

  /// Build a message overlay for temporary notifications.
  Widget _buildMessageOverlay() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.black87,
        borderRadius: BorderRadius.circular(8),
      ),
      child: const Text(
        'Message',
        style: TextStyle(color: Colors.white, fontSize: 14),
        textAlign: TextAlign.center,
      ),
    );
  }

  bool get _hasPendingMessage => false;

  /// Build the action buttons at the bottom of the screen.
  Widget _buildActionButtons(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8),
      color: Colors.black87,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          _actionButton(context, '↑', Direction.up),
          _actionButton(context, '↓', Direction.down),
          _actionButton(context, '←', Direction.left),
          _actionButton(context, '→', Direction.right),
          ElevatedButton(
            onPressed: widget.canMove ? _handleAttack : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.red[700],
              foregroundColor: Colors.white,
            ),
            child: const Text('Attack'),
          ),
          ElevatedButton(
            onPressed: widget.canMove ? _handleInventory : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.blue[700],
              foregroundColor: Colors.white,
            ),
            child: const Text('Items'),
          ),
          ElevatedButton(
            onPressed: widget.canMove ? () => _queueEvent(GameEvent.shop) : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.purple[700],
              foregroundColor: Colors.white,
            ),
            child: const Text('Shop'),
          ),
          ElevatedButton(
            onPressed: widget.canMove ? () => _queueEvent(GameEvent.upStairs) : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.green[700],
              foregroundColor: Colors.white,
            ),
            child: const Text('Up Stairs'),
          ),
          ElevatedButton(
            onPressed: widget.canMove ? () => _queueEvent(GameEvent.downStairs) : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.red[500],
              foregroundColor: Colors.white,
            ),
            child: const Text('Down Stairs'),
          ),
        ],
      ),
    );
  }

  /// Build a single action button.
  Widget _actionButton(BuildContext context, String label, Direction dir) {
    return SizedBox(
      width: 50,
      height: 50,
      child: ElevatedButton(
        onPressed: widget.canMove
            ? () => _handleMove(dir)
            : null,
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.grey[700],
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
        child: Text(
          label,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
      ),
    );
  }

  /// Handle player movement with collision detection.
  void _handleMove(Direction dir) {
    if (!widget.canMove) return;

    int dx = 0;
    int dy = 0;
    switch (dir) {
      case Direction.up:
        dy = -1;
        break;
      case Direction.down:
        dy = 1;
        break;
      case Direction.left:
        dx = -1;
        break;
      case Direction.right:
        dx = 1;
        break;
    }

    final newX = _lastPlayerX + dx;
    final newY = _lastPlayerY + dy;

    // Bounds check
    if (newX < 0 || newX >= 11 || newY < 0 || newY >= 11) return;

    // Collision check
    final targetKey = '$newX,$newY';
    final targetTile = widget.floorMap[targetKey];
    if (targetTile == null) return;

    final tileType = targetTile.type;

    // Block walls
    if (tileType == TileType.wall) return;

    // Block monsters (triggers combat)
    if (tileType == TileType.monster) {
      _queueEvent(GameEvent.combat);
      return;
    }

    // Block NPCs (triggers dialogue)
    if (tileType == TileType.npc) {
      _queueEvent(GameEvent.dialogue);
      return;
    }

    // Pick up items
    if (tileType == TileType.item) {
      _queueEvent(GameEvent.pickup);
      return;
    }

    // Open shop
    if (tileType == TileType.shop) {
      _queueEvent(GameEvent.shop);
      return;
    }

    // Boss tile
    if (tileType == TileType.boss) {
      _queueEvent(GameEvent.combat);
      return;
    }

    // Hidden room
    if (tileType == TileType.hiddenRoom) {
      _queueEvent(GameEvent.pickup);
      return;
    }

    // Stairs
    if (tileType == TileType.stairsUp) {
      _queueEvent(GameEvent.upStairs);
      return;
    }

    if (tileType == TileType.stairsDown) {
      _queueEvent(GameEvent.downStairs);
      return;
    }

    // Blocked by locked door
    if (tileType == TileType.door || tileType == TileType.lockedDoor) {
      widget.onShowMessage('Door is locked');
      return;
    }

    // Valid floor movement
    _lastPlayerX = newX;
    _lastPlayerY = newY;
    widget.onMove(dir);
    _queueEvent(GameEvent.move);
  }

  /// Queue an event for debounced processing.
  void _queueEvent(GameEvent event) {
    if (!_eventQueue.contains(event)) {
      _eventQueue.add(event);
    }
  }

  /// Process all queued events.
  void _processEventQueue() {
    for (final event in _eventQueue) {
      switch (event) {
        case GameEvent.combat:
          widget.onCombat(0);
          break;
        case GameEvent.dialogue:
          widget.onDialogue('NPC dialogue');
          break;
        case GameEvent.pickup:
          widget.onPickup('item');
          break;
        case GameEvent.shop:
          widget.onShop();
          break;
        case GameEvent.upStairs:
          widget.onUpStairs();
          break;
        case GameEvent.downStairs:
          widget.onDownStairs();
          break;
        case GameEvent.move:
          // Already handled in _handleMove.
          break;
      }
    }
    _eventQueue.clear();
  }

  /// Trigger combat with adjacent monster.
  void _handleAttack() {
    if (!widget.canMove) return;
    widget.onCombat(0);
  }

  /// Open inventory / item selection.
  void _handleInventory() {
    if (!widget.canMove) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Inventory opened')),
    );
  }

  // === Self-check ===

  /// Assert that the map was rendered at least once.
  bool get selfCheckMapRendered => _mapRendered;

  /// Assert that all tile types were accounted for in rendering.
  Set<TileType> get selfCheckRenderedTypes => Set.unmodifiable(_renderedTypes);
}
