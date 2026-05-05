/// 玩家状态管理：HP/ATK/DEF/Gold/EXP/Lv
///
/// Manages player attributes including health, attack, defense,
/// gold, experience, and level.

class PlayerMgr {
  PlayerMgr();

  bool _initialized = false;
  int _hp = 0;
  int _maxHp = 0;
  int _atk = 0;
  int _def = 0;
  int _gold = 0;
  int _exp = 0;
  int _level = 1;

  /// Initialize player attributes.
  ///
  /// Must be called before any attribute access or mutation.
  void initialize({
    int hp = 100,
    int maxHp = 100,
    int atk = 10,
    int def = 10,
    int gold = 0,
    int exp = 0,
    int level = 1,
  }) {
    _hp = hp;
    _maxHp = maxHp;
    _atk = atk;
    _def = def;
    _gold = gold;
    _exp = exp;
    _level = level;
    _initialized = true;
  }

  bool get isInitialized => _initialized;

  /// Current hit points. Throws [StateError] if not initialized.
  int get hp {
    _checkInit();
    return _hp;
  }

  /// Maximum hit points. Throws [StateError] if not initialized.
  int get maxHp {
    _checkInit();
    return _maxHp;
  }

  /// Attack power. Throws [StateError] if not initialized.
  int get atk {
    _checkInit();
    return _atk;
  }

  /// Defense power. Throws [StateError] if not initialized.
  int get def {
    _checkInit();
    return _def;
  }

  /// Gold count. Throws [StateError] if not initialized.
  int get gold {
    _checkInit();
    return _gold;
  }

  /// Experience points. Throws [StateError] if not initialized.
  int get exp {
    _checkInit();
    return _exp;
  }

  /// Player level. Throws [StateError] if not initialized.
  int get level {
    _checkInit();
    return _level;
  }

  /// Whether the player has died (HP <= 0).
  bool get isDead => _hp <= 0;

  /// Take damage, reducing HP. HP is clamped to [0].
  void takeDamage(int damage) {
    _checkInit();
    if (damage <= 0) return;
    _hp = (_hp - damage).clamp(0, _maxHp);
  }

  /// Heal HP by [amount]. HP is clamped to [_maxHp].
  /// Negative amounts are ignored.
  void heal(int amount) {
    _checkInit();
    if (amount <= 0) return;
    _hp = (_hp + amount).clamp(_hp, _maxHp);
  }

  /// Modify attack by [delta]. Result clamped to [0, 9999].
  void modifyAtk(int delta) {
    _checkInit();
    _atk = (_atk + delta).clamp(0, 9999);
  }

  /// Modify defense by [delta]. Result clamped to [0, 9999].
  void modifyDef(int delta) {
    _checkInit();
    _def = (_def + delta).clamp(0, 9999);
  }

  /// Modify gold by [delta]. Result clamped to [0, 999999].
  void modifyGold(int delta) {
    _checkInit();
    _gold = (_gold + delta).clamp(0, 999999);
  }

  /// Modify experience by [delta]. Result clamped to [0, 999999].
  void modifyExp(int delta) {
    _checkInit();
    _exp = (_exp + delta).clamp(0, 999999);
  }

  /// Reset all stats to initial defaults.
  /// Does NOT change [_initialized] — the player remains "initialized"
  /// so other subsystems can continue to use this instance.
  void reset() {
    _hp = 0;
    _atk = 0;
    _def = 0;
    _gold = 0;
    _exp = 0;
    _level = 1;
  }

  /// Serialize player state to a JSON-serializable map.
  Map<String, dynamic> toJson() {
    _checkInit();
    return {
      'hp': _hp,
      'atk': _atk,
      'def': _def,
      'gold': _gold,
      'exp': _exp,
      'level': _level,
    };
  }

  void _checkInit() {
    if (!_initialized) {
      throw StateError(
        'PlayerMgr not initialized. Call initialize() first.',
      );
    }
  }

  /// Convert current player state to a [PlayerState] data object.
  PlayerState toPlayerState() {
    return PlayerState(
      hp: _hp,
      maxHp: _maxHp,
      atk: _atk,
      def: _def,
      gold: _gold,
      exp: _exp,
      level: _level,
    );
  }
}
