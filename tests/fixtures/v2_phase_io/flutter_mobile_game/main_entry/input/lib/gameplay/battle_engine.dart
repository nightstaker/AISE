/// 回合制伤害计算：max(ATK−DEF, 1)
///
/// Calculates turn-based combat damage using the formula:
/// playerDamage = max(playerAtk - monsterDef, 1)
/// monsterDamage = max(monsterAtk - playerDef, 1)
///
/// The player attacks first. Battle continues until one side's HP reaches 0.

// ignore_for_file: public_member_api_docs

class BattleEngine {
  BattleEngine();

  bool _initialized = false;

  void initialize() {
    _initialized = true;
  }

  bool get isInitialized => _initialized;

  /// Calculate damage dealt by attacker to defender.
  /// Uses max(atk - def, 1) to ensure minimum 1 damage per hit.
  static int calculateDamage(int attackerAtk, int defenderDef) {
    final damage = attackerAtk - defenderDef;
    return damage > 0 ? damage : 1;
  }

  /// Calculate damage dealt by player to monster.
  static int calculatePlayerDamage(int playerAtk, int monsterDef) {
    return calculateDamage(playerAtk, monsterDef);
  }

  /// Calculate damage dealt by monster to player.
  static int calculateMonsterDamage(int monsterAtk, int playerDef) {
    return calculateDamage(monsterAtk, playerDef);
  }

  /// Calculate full battle outcome.
  ///
  /// Returns a BattleResult with:
  /// - Whether the player wins
  /// - Number of rounds for each side
  /// - Remaining HP for both sides
  BattleResult calculateRounds({
    required int playerHp,
    required int playerAtk,
    required int playerDef,
    required int monsterHp,
    required int monsterAtk,
    required int monsterDef,
  }) {
    if (!_initialized) throw StateError('BattleEngine not initialized');

    final playerDamage = calculatePlayerDamage(playerAtk, monsterDef);
    final monsterDamage = calculateMonsterDamage(monsterAtk, playerDef);

    final playerRoundsNeeded = _roundsToDefeat(monsterHp, playerDamage);
    final monsterRoundsNeeded = _roundsToDefeat(playerHp, monsterDamage);

    final playerWins = playerRoundsNeeded <= monsterRoundsNeeded;

    int playerHpRemaining = playerHp;
    int monsterHpRemaining = monsterHp;

    if (playerWins) {
      // Player wins: player attacks playerRoundsNeeded times
      final damageDealt = playerRoundsNeeded * playerDamage;
      monsterHpRemaining = (monsterHp - damageDealt).clamp(0, monsterHp);
      // Monster attacks playerRoundsNeeded - 1 times (player attacks first)
      final damageTaken = (playerRoundsNeeded - 1) * monsterDamage;
      playerHpRemaining = (playerHp - damageTaken).clamp(0, playerHp);
    } else {
      // Monster wins: monster attacks monsterRoundsNeeded times
      final damageDealt = monsterRoundsNeeded * monsterDamage;
      playerHpRemaining = (playerHp - damageDealt).clamp(0, playerHp);
      // Player attacks monsterRoundsNeeded - 1 times
      final monsterDmgTaken = (monsterRoundsNeeded - 1) * playerDamage;
      monsterHpRemaining = (monsterHp - monsterDmgTaken).clamp(0, monsterHp);
    }

    return BattleResult(
      playerWins: playerWins,
      playerRoundsNeeded: playerRoundsNeeded,
      monsterRoundsNeeded: monsterRoundsNeeded,
      playerHpRemaining: playerHpRemaining,
      monsterHpRemaining: monsterHpRemaining,
    );
  }

  /// Calculate rounds needed for player to defeat the monster.
  static int calculatePlayerRoundsNeeded(int playerAtk, int monsterDef, int monsterHp) {
    final damage = calculatePlayerDamage(playerAtk, monsterDef);
    return _roundsToDefeat(monsterHp, damage);
  }

  /// Calculate rounds needed for monster to defeat the player.
  static int calculateMonsterRoundsNeeded(int playerHp, int monsterAtk, int playerDef) {
    final damage = calculateMonsterDamage(monsterAtk, playerDef);
    return _roundsToDefeat(playerHp, damage);
  }

  static int _roundsToDefeat(int hp, int damagePerRound) {
    if (damagePerRound <= 0) return 999999;
    return (hp + damagePerRound - 1) ~/ damagePerRound;
  }
}

/// Result of a battle calculation.
class BattleResult {
  BattleResult({
    required this.playerWins,
    required this.playerRoundsNeeded,
    required this.monsterRoundsNeeded,
    required this.playerHpRemaining,
    required this.monsterHpRemaining,
  });

  final bool playerWins;
  final int playerRoundsNeeded;
  final int monsterRoundsNeeded;
  final int playerHpRemaining;
  final int monsterHpRemaining;
}
