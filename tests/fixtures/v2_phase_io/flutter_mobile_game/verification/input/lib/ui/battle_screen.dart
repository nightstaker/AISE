/// Battle screen — shows the turn-based combat animation and results.
///
/// Responsibilities:
/// - Display player and monster sprites (colored rectangles).
/// - Show turn-by-turn damage numbers and HP changes.
/// - Announce victory / defeat / flee outcomes.
/// - Return control to the game screen when combat ends.

import 'package:flutter/material.dart';

import '../data/models.dart';

/// Battle screen widget — shows turn-based combat animation.
class BattleScreen extends StatefulWidget {
  /// The monster the player is fighting.
  final MonsterState monster;

  /// Current player HP before battle starts.
  final int playerHp;

  /// Current player ATK.
  final int playerAtk;

  /// Current player DEF.
  final int playerDef;

  /// Whether the player won the battle.
  final bool playerWon;

  /// Total damage taken by the player in this battle.
  final int damageTaken;

  /// Whether the battle animation is still playing.
  final bool isAnimating;

  /// Callback when the battle ends (player clicks "Continue").
  final VoidCallback onBattleEnd;

  /// Callback to attempt fleeing from battle.
  final VoidCallback onFlee;

  const BattleScreen({
    super.key,
    this.monster = _defaultMonster,
    this.playerHp = 0,
    this.playerAtk = 0,
    this.playerDef = 0,
    this.playerWon = false,
    this.damageTaken = 0,
    this.isAnimating = false,
    this.onBattleEnd = _noop,
    this.onFlee = _noop,
  });

  static MonsterState get _defaultMonster => MonsterState(
    defId: 'dummy',
    name: 'dummy',
    currentHp: 0,
    maxHp: 0,
    atk: 0,
    def: 0,
    expReward: 0,
    goldReward: 0,
    isBoss: false,
  );
  static void _noop() {}

  @override
  State<BattleScreen> createState() => _BattleScreenState();

  /// Initialize this screen. Called by the app's lifecycle init.
  void initialize() {
    // BattleScreen is stateful; initialization handled in initState.
  }

  bool get isInitialized => true;
}

class _BattleScreenState extends State<BattleScreen> {
  /// Animation progress (0.0 to 1.0).
  double _progress = 0.0;

  @override
  void initState() {
    super.initState();
    if (widget.isAnimating) {
      _startAnimation();
    }
  }

  void _startAnimation() {
    const steps = 30;
    for (int i = 0; i <= steps; i++) {
      Future.delayed(Duration(milliseconds: i * 50), () {
        if (mounted) {
          setState(() => _progress = i / steps);
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black87,
      body: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // Monster display
          Expanded(
            flex: 2,
            child: _buildMonsterArea(context),
          ),
          // VS divider
          Container(
            color: Colors.red[900],
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: const Text(
              'VS',
              style: TextStyle(
                color: Colors.white,
                fontSize: 24,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
          // Player display
          Expanded(
            flex: 2,
            child: _buildPlayerArea(context),
          ),
          // Battle log
          Expanded(
            flex: 1,
            child: _buildBattleLog(context),
          ),
          // Action buttons
          if (!widget.isAnimating)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  // Flee button
                  ElevatedButton(
                    onPressed: widget.onFlee,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.grey[600],
                      padding: const EdgeInsets.symmetric(
                        horizontal: 32,
                        vertical: 12,
                      ),
                    ),
                    child: const Text(
                      '逃跑',
                      style: TextStyle(fontSize: 16, color: Colors.white),
                    ),
                  ),
                  const SizedBox(width: 16),
                  // Continue button
                  ElevatedButton(
                    onPressed: widget.onBattleEnd,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.amber[700],
                      padding: const EdgeInsets.symmetric(
                        horizontal: 48,
                        vertical: 16,
                      ),
                    ),
                    child: const Text(
                      '继续',
                      style: TextStyle(fontSize: 18, color: Colors.white),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildMonsterArea(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // Monster sprite placeholder
          Container(
            width: 120,
            height: 120,
            decoration: BoxDecoration(
              color: Colors.red[400],
              borderRadius: BorderRadius.circular(8),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            widget.monster.name,
            style: const TextStyle(color: Colors.white, fontSize: 16),
          ),
          Text(
            'HP: ${widget.playerHp}',
            style: const TextStyle(color: Colors.red, fontSize: 14),
          ),
        ],
      ),
    );
  }

  Widget _buildPlayerArea(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // Player sprite placeholder
          Container(
            width: 100,
            height: 100,
            decoration: BoxDecoration(
              color: Colors.blue[400],
              borderRadius: BorderRadius.circular(8),
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            'Player',
            style: TextStyle(color: Colors.white, fontSize: 16),
          ),
          Text(
            'HP: ${widget.playerHp} ATK: ${widget.playerAtk} DEF: ${widget.playerDef}',
            style: const TextStyle(color: Colors.white70, fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _buildBattleLog(BuildContext context) {
    final messages = <String>[];

    if (widget.playerWon) {
      messages.add('Victory!');
      messages.add('Monster defeated.');
      messages.add('Damage taken: ${widget.damageTaken}');
    } else {
      messages.add('Defeat!');
      messages.add('You have been defeated by ${widget.monster.name}.');
      messages.add('Gold penalty applied.');
    }

    return Container(
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.black54,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: messages.map((msg) => Text(
          msg,
          style: const TextStyle(color: Colors.white, fontSize: 14),
        )).toList(),
      ),
    );
  }
}
