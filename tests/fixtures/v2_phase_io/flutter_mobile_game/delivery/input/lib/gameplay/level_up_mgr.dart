/// EXP 升级公式 + 属性提升
///
/// Manages player experience, leveling up, and stat increases.

// ignore_for_file: public_member_api_docs

class LevelUpMgr {
  LevelUpMgr();

  bool _initialized = false;
  int _level = 1;
  int _exp = 0;
  int _hp = 0;
  int _atk = 0;
  int _def = 0;
  int _baseHp = 0;
  int _baseAtk = 0;
  int _baseDef = 0;
  int _hpPerLevel = 0;
  int _atkPerLevel = 0;
  int _defPerLevel = 0;
  int _expThreshold = 100;

  int get level => _checkInit(_level);
  int get exp => _checkInit(_exp);
  int get hp => _checkInit(_hp);
  int get atk => _checkInit(_atk);
  int get def => _checkInit(_def);
  bool get isInitialized => _initialized;

  void initialize({
    int initialLevel = 1,
    int initialExp = 0,
    int baseHp = 100,
    int baseAtk = 10,
    int baseDef = 10,
    int hpPerLevel = 20,
    int atkPerLevel = 2,
    int defPerLevel = 2,
    int expThreshold = 100,
  }) {
    _level = initialLevel;
    _exp = initialExp;
    _baseHp = baseHp;
    _baseAtk = baseAtk;
    _baseDef = baseDef;
    _hpPerLevel = hpPerLevel;
    _atkPerLevel = atkPerLevel;
    _defPerLevel = defPerLevel;
    _expThreshold = expThreshold;
    _hp = baseHp;
    _atk = baseAtk;
    _def = baseDef;
    _initialized = true;
  }

  void addExp(int amount) {
    _checkInit();
    if (amount < 0) return;
    _exp += amount;
  }

  void consumeExp(int amount) {
    _checkInit();
    if (amount < 0) return;
    _exp = (_exp - amount).clamp(0, _exp);
  }

  void levelUp() {
    _checkInit();
    _level++;
    _hp = _baseHp + (_level - 1) * _hpPerLevel;
    _atk = _baseAtk + (_level - 1) * _atkPerLevel;
    _def = _baseDef + (_level - 1) * _defPerLevel;
  }

  bool checkLevelUp() {
    _checkInit();
    if (_exp >= _expThreshold) {
      _exp -= _expThreshold;
      levelUp();
      return true;
    }
    return false;
  }

  bool canLevelUp() {
    _checkInit();
    return _exp >= _expThreshold;
  }

  int getExpThreshold() {
    _checkInit();
    return _expThreshold;
  }

  void reset() {
    _checkInit();
    _level = 1;
    _exp = 0;
    _hp = _baseHp;
    _atk = _baseAtk;
    _def = _baseDef;
  }

  Map<String, dynamic> toJson() {
    return {
      'level': _level,
      'exp': _exp,
      'hp': _hp,
      'atk': _atk,
      'def': _def,
      'baseHp': _baseHp,
      'baseAtk': _baseAtk,
      'baseDef': _baseDef,
      'hpPerLevel': _hpPerLevel,
      'atkPerLevel': _atkPerLevel,
      'defPerLevel': _defPerLevel,
      'expThreshold': _expThreshold,
    };
  }

  factory LevelUpMgr.fromJson(Map<String, dynamic> json) {
    final mgr = LevelUpMgr();
    mgr._level = json['level'] as int;
    mgr._exp = json['exp'] as int;
    mgr._hp = json['hp'] as int;
    mgr._atk = json['atk'] as int;
    mgr._def = json['def'] as int;
    mgr._baseHp = json['baseHp'] as int;
    mgr._baseAtk = json['baseAtk'] as int;
    mgr._baseDef = json['baseDef'] as int;
    mgr._hpPerLevel = json['hpPerLevel'] as int;
    mgr._atkPerLevel = json['atkPerLevel'] as int;
    mgr._defPerLevel = json['defPerLevel'] as int;
    mgr._expThreshold = json['expThreshold'] as int;
    mgr._initialized = true;
    return mgr;
  }

  void _checkInit([dynamic returnValue]) {
    if (!_initialized) throw StateError('LevelUpMgr not initialized');
    return returnValue;
  }
}
