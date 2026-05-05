// ignore_for_file: public_member_api_docs

/// Internationalization manager — Chinese / English translation lookup.
///
/// The built-in dictionary covers the keys used by the game UI.  In a
/// production build the same interface would load from `assets/i18n.json`
/// at runtime; the embedded map below keeps tests and the app working
/// without external assets.
class I18nMgr {
  I18nMgr();

  bool _initialized = false;

  /// Current locale code — `'zh'` for Chinese, `'en'` for English.
  String currentLanguage = 'zh';

  // ------------------------------------------------------------------
  // Built-in dictionary (production would load from i18n.json)
  // ------------------------------------------------------------------

  final Map<String, Map<String, String>> _dict = {
    'zh': {
      'start_game': '开始游戏',
      'continue_game': '继续游戏',
      'settings': '设置',
      'about': '关于',
      'exit_game': '退出游戏',
      'back': '返回',
      'next_page': '下一页',
      'previous_page': '上一页',
      'hp': '生命',
      'atk': '攻击',
      'def': '防御',
      'gold': '金币',
      'exp': '经验',
      'level': '等级',
      'floor': '楼层',
      'up': '上',
      'down': '下',
      'left': '左',
      'right': '右',
      'attack': '攻击',
      'inventory': '道具',
      'key_yellow': '黄钥匙',
      'key_blue': '蓝钥匙',
      'key_red': '红钥匙',
      'potion_red': '红血瓶',
      'potion_blue': '蓝血瓶',
      'gem_red': '红宝石',
      'gem_blue': '蓝宝石',
      'shop': '商店',
      'buy': '购买',
      'sell': '出售',
      'price': '价格',
      'not_enough_gold': '金币不足',
      'dialogue': '对话',
      'boss': 'BOSS',
      'victory': '胜利',
      'defeat': '失败',
      'game_over': '游戏结束',
      'save': '存档',
      'load': '读档',
      'delete_save': '删除存档',
      'confirm': '确认',
      'cancel': '取消',
      'music': '音乐',
      'sfx': '音效',
      'language': '语言',
      'clear_save': '清除存档',
      'welcome': '欢迎来到魔塔',
      'hint': '提示',
      'tutorial': '新手教程',
      'instructions': '使用说明',
      'version': '版本',
      'credits': '制作人员',
      'hidden_room': '隐藏房间',
      'stairs_up': '上楼',
      'stairs_down': '下楼',
      'door': '门',
      'wall': '墙壁',
    },
    'en': {
      'start_game': 'Start Game',
      'continue_game': 'Continue',
      'settings': 'Settings',
      'about': 'About',
      'exit_game': 'Exit',
      'back': 'Back',
      'next_page': 'Next',
      'previous_page': 'Prev',
      'hp': 'HP',
      'atk': 'ATK',
      'def': 'DEF',
      'gold': 'Gold',
      'exp': 'EXP',
      'level': 'Lv',
      'floor': 'Floor',
      'up': 'Up',
      'down': 'Down',
      'left': 'Left',
      'right': 'Right',
      'attack': 'Attack',
      'inventory': 'Inventory',
      'key_yellow': 'Yellow Key',
      'key_blue': 'Blue Key',
      'key_red': 'Red Key',
      'potion_red': 'Red Potion',
      'potion_blue': 'Blue Potion',
      'gem_red': 'Ruby',
      'gem_blue': 'Sapphire',
      'shop': 'Shop',
      'buy': 'Buy',
      'sell': 'Sell',
      'price': 'Price',
      'not_enough_gold': 'Not enough gold',
      'dialogue': 'Dialogue',
      'boss': 'BOSS',
      'victory': 'Victory',
      'defeat': 'Defeat',
      'game_over': 'Game Over',
      'save': 'Save',
      'load': 'Load',
      'delete_save': 'Delete Save',
      'confirm': 'Confirm',
      'cancel': 'Cancel',
      'music': 'Music',
      'sfx': 'SFX',
      'language': 'Language',
      'clear_save': 'Clear Save',
      'welcome': 'Welcome to Magic Tower',
      'hint': 'Hint',
      'tutorial': 'Tutorial',
      'instructions': 'Instructions',
      'version': 'Version',
      'credits': 'Credits',
      'hidden_room': 'Hidden Room',
      'stairs_up': 'Up Stairs',
      'stairs_down': 'Down Stairs',
      'door': 'Door',
      'wall': 'Wall',
    },
  };

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------

  void initialize() {
    _initialized = true;
  }

  void setLanguage(String language) {
    if (_dict.containsKey(language)) {
      currentLanguage = language;
    } else {
      // Fallback to Chinese if the requested language is unsupported.
      currentLanguage = 'zh';
    }
  }

  /// Translate a key.  Falls back to the key itself when the key or
  /// the current language is missing from the dictionary.
  String translate(String key) {
    final langData = _dict[currentLanguage];
    if (langData == null) return key;
    return langData[key] ?? key;
  }

  /// Check whether a key exists in the current language.
  bool hasTranslation(String key) {
    final langData = _dict[currentLanguage];
    return langData != null && langData.containsKey(key);
  }

  /// Return the list of supported locale codes.
  List<String> getSupportedLanguages() => _dict.keys.toList();
}
