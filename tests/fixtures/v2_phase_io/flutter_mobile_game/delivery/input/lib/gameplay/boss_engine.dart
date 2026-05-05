/// Multi-phase boss battle engine
///
/// Manages multi-phase boss battles with phase transitions
/// when HP drops below thresholds. Supports boss turn logic,
/// special attacks per phase, and full battle simulation.

// ─────────────────────────────────────────────────────────────────────────────
// Boss AI action types
// ─────────────────────────────────────────────────────────────────────────────

/// Types of actions a boss can take during its turn.
enum BossAction {
  /// Normal attack — uses base ATK/DEF stats.
  attack,

  /// Special attack — uses phase-specific special ability with bonus damage.
  specialAttack,

  /// Defensive stance — reduces incoming damage for one round.
  defend,

  /// Enrage — when HP is critically low, boss enters enrage mode with
  /// increased ATK but reduced DEF.
  enrage,
}

// ─────────────────────────────────────────────────────────────────────────────
// BossPhase — phase definition
// ─────────────────────────────────────────────────────────────────────────────

/// A single phase in a multi-phase boss battle.
///
/// Each phase defines the boss's stats at a particular HP threshold,
/// its special attack name (for UI display), and an AI weight table
/// that determines action probabilities.
class BossPhase {
  BossPhase({
    required this.phaseId,
    required this.hpThreshold,
    required this.atk,
    required this.def,
    required this.special,
    this.specialDamageBonus = 0,
    this.defendReduction = 0,
    this.enrageAtkBonus = 0,
    this.enrageDefPenalty = 0,
  });

  /// Unique phase identifier (1-based, ascending).
  final int phaseId;

  /// HP threshold — when boss HP drops to or below this value,
  /// the boss transitions to the next phase.
  final int hpThreshold;

  /// Attack power in this phase.
  int atk;

  /// Defense power in this phase.
  int def;

  /// Special attack name / identifier (e.g. "fireBreath").
  final String special;

  /// Additional damage dealt when using [special].
  final int specialDamageBonus;

  /// Damage reduction factor when boss uses [BossAction.defend].
  final int defendReduction;

  /// ATK bonus when boss enters enrage mode.
  final int enrageAtkBonus;

  /// DEF penalty when boss enters enrage mode.
  final int enrageDefPenalty;

  /// Weight for [BossAction.attack] in AI decision. Higher = more likely.
  int get attackWeight => 5;

  /// Weight for [BossAction.specialAttack] in AI decision.
  int get specialAttackWeight => phaseId >= 2 ? 4 : 2;

  /// Weight for [BossAction.defend] in AI decision.
  int get defendWeight => phaseId >= 2 ? 3 : 0;

  /// Weight for [BossAction.enrage] — only when HP is critical.
  int get enrageWeight => hpThreshold > 0 && hpThreshold < 100 ? 8 : 0;

  // ── serialisation ────────────────────────────────────────────────────

  Map<String, dynamic> toJson() {
    return {
      'phaseId': phaseId,
      'hpThreshold': hpThreshold,
      'atk': atk,
      'def': def,
      'special': special,
      'specialDamageBonus': specialDamageBonus,
      'defendReduction': defendReduction,
      'enrageAtkBonus': enrageAtkBonus,
      'enrageDefPenalty': enrageDefPenalty,
    };
  }

  factory BossPhase.fromJson(Map<String, dynamic> json) {
    return BossPhase(
      phaseId: json['phaseId'] as int,
      hpThreshold: json['hpThreshold'] as int,
      atk: json['atk'] as int,
      def: json['def'] as int,
      special: json['special'] as String,
      specialDamageBonus: json['specialDamageBonus'] as int? ?? 0,
      defendReduction: json['defendReduction'] as int? ?? 0,
      enrageAtkBonus: json['enrageAtkBonus'] as int? ?? 0,
      enrageDefPenalty: json['enrageDefPenalty'] as int? ?? 0,
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// BossTurnResult — result of one boss turn
// ─────────────────────────────────────────────────────────────────────────────

/// The outcome of a single boss turn, describing what action was taken
/// and how much damage the player receives.
class BossTurnResult {
  BossTurnResult({
    required this.action,
    required this.damage,
    required this.message,
    this.defending = false,
  });

  /// The action the boss chose.
  final BossAction action;

  /// Damage dealt to the player.
  final int damage;

  /// Human-readable message for the battle log.
  final String message;

  /// Whether the boss entered a defensive stance this turn.
  final bool defending;
}

// ─────────────────────────────────────────────────────────────────────────────
// BattlePhaseResult — result of a full battle simulation
// ─────────────────────────────────────────────────────────────────────────────

/// Result of simulating a full multi-phase boss battle.
class BattlePhaseResult {
  BattlePhaseResult({
    required this.playerWins,
    required this.finalPhase,
    required this.playerHpRemaining,
    required this.bossHpRemaining,
    required this.turns,
    required this.turnLog,
  });

  /// Whether the player defeated the boss.
  final bool playerWins;

  /// The final phase the boss was in when the battle ended.
  final int finalPhase;

  /// Player HP remaining after the battle.
  final int playerHpRemaining;

  /// Boss HP remaining (0 if defeated).
  final int bossHpRemaining;

  /// Total number of combat turns.
  final int turns;

  /// Battle log — one entry per turn.
  final List<String> turnLog;
}

// ─────────────────────────────────────────────────────────────────────────────
// BossEngine — main engine
// ─────────────────────────────────────────────────────────────────────────────

/// Multi-phase boss battle engine.
///
/// Manages boss state, phase transitions, boss turn logic, and full
/// battle simulation. Uses static damage calculation matching the
/// game's standard formula: max(atk - def, 1).
class BossEngine {
  BossEngine();

  bool _initialized = false;
  int _bossHp = 0;
  int _playerHp = 0;
  int _playerMaxHp = 0;
  int _bossAtk = 0;
  int _bossDef = 0;
  List<BossPhase> _phases = [];
  int _currentPhase = 1;
  bool _isDefeated = false;
  bool _playerDefending = false;
  int _turnCount = 0;
  int _playerAtk = 0;
  int _playerDef = 0;

  // ── accessors ────────────────────────────────────────────────────────

  int get bossHp {
    _checkInit();
    return _bossHp;
  }

  int get playerHp {
    _checkInit();
    return _playerHp;
  }

  int get playerMaxHp {
    _checkInit();
    return _playerMaxHp;
  }

  int get bossAtk {
    _checkInit();
    return _bossAtk;
  }

  int get bossDef {
    _checkInit();
    return _bossDef;
  }

  int get phaseCount {
    _checkInit();
    return _phases.length;
  }

  int get currentPhase {
    _checkInit();
    return _currentPhase;
  }

  bool get isDefeated {
    _checkInit();
    return _isDefeated;
  }

  bool get playerDefending {
    _checkInit();
    return _playerDefending;
  }

  int get turnCount {
    _checkInit();
    return _turnCount;
  }

  bool get isInitialized => _initialized;

  BossPhase? get currentPhaseInfo {
    for (final phase in _phases) {
      if (phase.phaseId == _currentPhase) return phase;
    }
    return null;
  }

  // ── lifecycle ────────────────────────────────────────────────────────

  /// Initialize the boss with full battle context.
  ///
  /// [hp], [atk], [def] are the base boss stats (phase 1).
  /// [phases] defines all phases — phase 1 must have [phaseId] == 1
  /// and [hpThreshold] >= the boss's starting HP.
  void initialize({
    required int hp,
    required int atk,
    required int def,
    required List<BossPhase> phases,
  }) {
    if (phases.isEmpty) {
      throw ArgumentError('Boss must have at least one phase');
    }

    _bossHp = hp;
    _playerHp = hp; // placeholder — setPlayerHp must be called before battle
    _playerMaxHp = hp;
    _bossAtk = atk;
    _bossDef = def;
    _phases = List.from(phases);
    _currentPhase = phases.first.phaseId;
    _isDefeated = false;
    _playerDefending = false;
    _turnCount = 0;
    _initialized = true;
  }

  /// Set the player's HP for battle simulation.
  void setPlayerHp(int hp) {
    _checkInit();
    _playerHp = hp;
    _playerMaxHp = hp;
  }

  /// Set the player's ATK and DEF for battle simulation.
  void setPlayerStats({required int atk, required int def}) {
    _checkInit();
    _playerAtk = atk;
    _playerDef = def;
  }

  // ── boss damage ──────────────────────────────────────────────────────

  /// Apply damage to the boss. Triggers phase transitions and checks
  /// for defeat.
  ///
  /// Returns the new HP after damage.
  int takeDamage(int damage) {
    _checkInit();
    if (_isDefeated) return _bossHp;

    _bossHp = (_bossHp - damage).clamp(0, _bossHp + damage);

    if (_bossHp <= 0) {
      _isDefeated = true;
      return 0;
    }

    // Phase transition: find the highest phase whose threshold is <= current HP
    for (var i = _phases.length - 1; i >= 0; i--) {
      final phase = _phases[i];
      if (phase.hpThreshold <= _bossHp && phase.phaseId > _currentPhase) {
        _currentPhase = phase.phaseId;
        _bossAtk = phase.atk;
        _bossDef = phase.def;
        return _bossHp;
      }
    }

    return _bossHp;
  }

  /// Heal the boss. Does not revive a defeated boss.
  void heal(int amount) {
    _checkInit();
    if (_isDefeated) return;
    _bossHp = (_bossHp + amount).clamp(0, 99999);
  }

  // ── boss turn logic ─────────────────────────────────────────────────

  /// Simulate one boss turn. Returns a [BossTurnResult].
  ///
  /// The boss AI picks an action based on current phase weights and
  /// the boss's current state.
  BossTurnResult bossTurn() {
    _checkInit();
    if (_isDefeated) {
      return BossTurnResult(
        action: BossAction.attack,
        damage: 0,
        message: 'Boss is defeated',
      );
    }

    _turnCount++;
    _playerDefending = false; // reset each turn

    // Pick action based on weights
    final action = _pickAction();

    // Calculate damage using internal formula
    final damagePerHit = calculateMonsterDamage(_bossAtk, _playerDef);

    switch (action) {
      case BossAction.attack:
        final damage = _playerDefending
            ? (damagePerHit * 0.5).toInt().clamp(1, damagePerHit)
            : damagePerHit;
        return BossTurnResult(
          action: BossAction.attack,
          damage: damage,
          message: 'Boss attacks for $damage damage',
        );

      case BossAction.specialAttack:
        final phase = currentPhaseInfo;
        final specialDmg = phase != null
            ? damagePerHit + phase.specialDamageBonus
            : damagePerHit;
        final actualDmg = _playerDefending
            ? (specialDmg * 0.5).toInt().clamp(1, specialDmg)
            : specialDmg;
        return BossTurnResult(
          action: BossAction.specialAttack,
          damage: actualDmg,
          message: 'Boss uses ${phase?.special ?? "special"} for $actualDmg damage!',
        );

      case BossAction.defend:
        _playerDefending = true;
        return BossTurnResult(
          action: BossAction.defend,
          damage: 0,
          message: 'Boss braces for impact — incoming damage reduced!',
          defending: true,
        );

      case BossAction.enrage:
        final enrageDmg = (damagePerHit * 1.5).toInt().clamp(
          damagePerHit,
          damagePerHit * 2,
        );
        return BossTurnResult(
          action: BossAction.enrage,
          damage: enrageDmg,
          message: 'Boss enrages! Dealing $enrageDmg damage!',
        );
    }
  }

  BossAction _pickAction() {
    final phase = currentPhaseInfo;
    if (phase == null) return BossAction.attack;

    // Enrage: if HP is below 25% of max, strongly prefer enrage
    final hpPercent = _bossHp / _playerMaxHp;
    if (hpPercent <= 0.25 && phase.enrageWeight > 0) {
      return BossAction.enrage;
    }

    // Build weighted pool
    final weights = <BossAction, int>{
      BossAction.attack: phase.attackWeight,
      BossAction.specialAttack: phase.specialAttackWeight,
      BossAction.defend: phase.defendWeight,
    };

    if (hpPercent <= 0.25) {
      weights[BossAction.enrage] = phase.enrageWeight;
    }

    return _weightedRandom(weights);
  }

  BossAction _weightedRandom(Map<BossAction, int> weights) {
    final total = weights.values.fold<int>(0, (a, b) => a + b);
    var roll = DateTime.now().millisecondsSinceEpoch % total;
    for (final entry in weights.entries) {
      if (roll < entry.value) return entry.key;
      roll -= entry.value;
    }
    return BossAction.attack;
  }

  // ── player turn (convenience) ────────────────────────────────────────

  /// Apply damage to the boss and simulate the player's turn in
  /// a full battle loop.
  ///
  /// Returns the boss HP after the player's attack.
  int playerAttack(int damage) {
    _checkInit();
    return takeDamage(damage);
  }

  // ── full battle simulation ───────────────────────────────────────────

  /// Simulate a full boss battle from start to finish.
  ///
  /// Each round: player attacks first, then boss attacks.
  /// Returns a [BattlePhaseResult] with the outcome.
  BattlePhaseResult simulateBattle({
    required int playerHp,
    required int playerAtk,
    required int playerDef,
    int maxRounds = 100,
  }) {
    _checkInit();

    setPlayerHp(playerHp);
    setPlayerStats(atk: playerAtk, def: playerDef);

    var pHp = playerHp;
    var bHp = _bossHp;
    var turns = 0;
    final log = <String>[];

    while (turns < maxRounds && !_isDefeated && bHp > 0 && pHp > 0) {
      turns++;
      _playerDefending = false;

      // Player attacks
      final playerDmg = calculatePlayerDamage(playerAtk, _bossDef);
      final newBHp = (bHp - playerDmg).clamp(0, bHp);
      bHp = newBHp;

      log.add('Player deals $playerDmg damage. Boss HP: $bHp');

      if (bHp <= 0) {
        _isDefeated = true;
        break;
      }

      // Phase transition check
      for (var i = _phases.length - 1; i >= 0; i--) {
        final phase = _phases[i];
        if (phase.hpThreshold <= bHp && phase.phaseId > _currentPhase) {
          _currentPhase = phase.phaseId;
          _bossAtk = phase.atk;
          _bossDef = phase.def;
          log.add('Boss transitions to Phase ${phase.phaseId}!');
          break;
        }
      }

      // Boss attacks
      final bossResult = bossTurn();
      pHp = (pHp - bossResult.damage).clamp(0, pHp);
      log.add(bossResult.message);

      if (pHp <= 0) {
        break;
      }
    }

    return BattlePhaseResult(
      playerWins: _isDefeated && bHp <= 0,
      finalPhase: _currentPhase,
      playerHpRemaining: pHp,
      bossHpRemaining: bHp,
      turns: turns,
      turnLog: log,
    );
  }

  // ── special attack info ──────────────────────────────────────────────

  /// Get the special attack name for the current phase.
  String specialAttack() {
    _checkInit();
    if (_isDefeated) return '';
    for (final phase in _phases) {
      if (phase.phaseId == _currentPhase) return phase.special;
    }
    return '';
  }

  /// Get phase info by ID.
  BossPhase? getPhaseInfo(int phaseId) {
    _checkInit();
    for (final phase in _phases) {
      if (phase.phaseId == phaseId) return phase;
    }
    return null;
  }

  // ── serialization ────────────────────────────────────────────────────

  Map<String, dynamic> toJson() {
    return {
      'bossHp': _bossHp,
      'bossAtk': _bossAtk,
      'bossDef': _bossDef,
      'playerHp': _playerHp,
      'playerMaxHp': _playerMaxHp,
      'playerAtk': _playerAtk,
      'playerDef': _playerDef,
      'currentPhase': _currentPhase,
      'isDefeated': _isDefeated,
      'playerDefending': _playerDefending,
      'turnCount': _turnCount,
      'phases': _phases.map((p) => p.toJson()).toList(),
    };
  }

  factory BossEngine.fromJson(Map<String, dynamic> json) {
    final engine = BossEngine();
    engine._bossHp = json['bossHp'] as int;
    engine._bossAtk = json['bossAtk'] as int;
    engine._bossDef = json['bossDef'] as int;
    engine._playerHp = json['playerHp'] as int;
    engine._playerMaxHp = json['playerMaxHp'] as int;
    engine._playerAtk = json['playerAtk'] as int;
    engine._playerDef = json['playerDef'] as int;
    engine._currentPhase = json['currentPhase'] as int;
    engine._isDefeated = json['isDefeated'] as bool;
    engine._playerDefending = json['playerDefending'] as bool? ?? false;
    engine._turnCount = json['turnCount'] as int? ?? 0;
    engine._phases = (json['phases'] as List<dynamic>)
        .map((e) => BossPhase.fromJson(e as Map<String, dynamic>))
        .toList();
    engine._initialized = true;
    return engine;
  }

  // ── reset ────────────────────────────────────────────────────────────

  /// Reset the boss to its initial state.
  void reset() {
    _checkInit();
    if (_phases.isEmpty) return;

    _bossHp = _phases.first.hpThreshold + 1;
    _bossAtk = _phases.first.atk;
    _bossDef = _phases.first.def;
    _currentPhase = _phases.first.phaseId;
    _isDefeated = false;
    _playerDefending = false;
    _turnCount = 0;
  }

  // ── internal ─────────────────────────────────────────────────────────

  /// Calculate damage dealt by attacker to defender.
  /// Uses max(atk - def, 1) to ensure minimum 1 damage per hit.
  static int calculateDamage(int attackerAtk, int defenderDef) {
    final damage = attackerAtk - defenderDef;
    return damage > 0 ? damage : 1;
  }

  /// Calculate damage dealt by player to boss.
  static int calculatePlayerDamage(int playerAtk, int bossDef) {
    return calculateDamage(playerAtk, bossDef);
  }

  /// Calculate damage dealt by boss to player.
  static int calculateMonsterDamage(int monsterAtk, int playerDef) {
    return calculateDamage(monsterAtk, playerDef);
  }

  void _checkInit([dynamic returnValue]) {
    if (!_initialized) throw StateError('BossEngine not initialized');
    return returnValue;
  }
}
