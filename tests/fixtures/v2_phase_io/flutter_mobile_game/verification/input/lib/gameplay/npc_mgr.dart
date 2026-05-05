/// 剧情对话管理 + 线索提示
///
/// Manages NPC dialogues, story clues, and interaction state.

// ignore_for_file: public_member_api_docs

class NPCMgr {
  NPCMgr();

  bool _initialized = false;
  final Map<String, NPCData> _npcs = {};
  final Map<String, String> _clues = {};
  String? _currentNPCId;
  int _currentPage = -1;

  int get dialogueCount => _checkInit(_npcs.length);
  int get clueCount => _checkInit(_clues.length);
  String? get currentNPCId => _initialized ? _currentNPCId : null;
  int get currentPage => _initialized ? _currentPage : -1;
  bool get isInitialized => _initialized;

  void initialize() {
    _initialized = true;
  }

  // === NPC Management ===

  void addNPC(String id, String name, [List<DialoguePage>? dialogues]) {
    _checkInit();
    _npcs[id] = NPCData(id: id, name: name, dialogues: dialogues ?? []);
  }

  bool removeNPC(String id) {
    _checkInit();
    if (_npcs.containsKey(id)) {
      _npcs.remove(id);
      if (_currentNPCId == id) _currentNPCId = null;
      return true;
    }
    return false;
  }

  bool hasNPC(String id) {
    _checkInit();
    return _npcs.containsKey(id);
  }

  String? getNPCName(String id) {
    _checkInit();
    return _npcs[id]?.name;
  }

  // === Dialogue Management ===

  bool startDialogue(String npcId) {
    _checkInit();
    final npc = _npcs[npcId];
    if (npc == null || npc.dialogues.isEmpty) return false;
    _currentNPCId = npcId;
    _currentPage = 0;
    return true;
  }

  void nextPage() {
    _checkInit();
    if (_currentNPCId == null) return;
    final npc = _npcs[_currentNPCId];
    if (npc == null || _currentPage < 0 || _currentPage >= npc.dialogues.length) return;
    final page = npc.dialogues[_currentPage];
    if (page.nextPage != null && page.nextPage! < npc.dialogues.length) {
      _currentPage = page.nextPage!;
    }
  }

  bool isOnDialogue() {
    _checkInit();
    return _currentNPCId != null && _currentPage >= 0;
  }

  void endDialogue() {
    _checkInit();
    _currentNPCId = null;
    _currentPage = -1;
  }

  List<String> getLines() {
    _checkInit();
    if (_currentNPCId == null || _currentPage < 0) return [];
    final npc = _npcs[_currentNPCId];
    if (npc == null || _currentPage >= npc.dialogues.length) return [];
    return npc.dialogues[_currentPage].lines;
  }

  // === Clue Management ===

  void addClue(String id, String text) {
    _checkInit();
    _clues[id] = text;
  }

  bool hasClue(String id) {
    _checkInit();
    return _clues.containsKey(id);
  }

  String? getClueText(String id) {
    _checkInit();
    return _clues[id];
  }

  Map<String, String> getClues() {
    _checkInit();
    return Map.unmodifiable(_clues);
  }

  void clearAll() {
    _checkInit();
    _npcs.clear();
    _clues.clear();
    _currentNPCId = null;
    _currentPage = -1;
  }

  // === Serialization ===

  Map<String, dynamic> toJson() {
    return {
      'npcs': _npcs.values.map((npc) => npc.toJson()).toList(),
      'clues': _clues,
    };
  }

  factory NPCMgr.fromJson(Map<String, dynamic> json) {
    final mgr = NPCMgr();
    mgr._initialized = true;
    mgr._npcs = (json['npcs'] as List<dynamic>)
        .map((e) => NPCData.fromJson(e as Map<String, dynamic>))
        .fold<Map<String, NPCData>>(
          {},
          (map, npc) => map..[npc.id] = npc,
        );
    mgr._clues = (json['clues'] as Map<String, dynamic>).cast<String, String>();
    return mgr;
  }

  void _checkInit([dynamic returnValue]) {
    if (!_initialized) throw StateError('NPCMgr not initialized');
    return returnValue;
  }
}

/// Dialogue page containing text lines and navigation.
class DialoguePage {
  DialoguePage({
    required this.lines,
    this.nextPage,
  });

  final List<String> lines;
  final int? nextPage;
}

/// NPC data including name and dialogues.
class NPCData {
  NPCData({
    required this.id,
    required this.name,
    required this.dialogues,
  });

  final String id;
  final String name;
  final List<DialoguePage> dialogues;

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'dialogues': dialogues.map((d) => {
        'lines': d.lines,
        'nextPage': d.nextPage,
      }).toList(),
    };
  }

  factory NPCData.fromJson(Map<String, dynamic> json) {
    return NPCData(
      id: json['id'] as String,
      name: json['name'] as String,
      dialogues: (json['dialogues'] as List<dynamic>)
          .map((d) {
            final map = d as Map<String, dynamic>;
            return DialoguePage(
              lines: (map['lines'] as List<dynamic>).cast<String>(),
              nextPage: map['nextPage'] as int?,
            );
          })
          .toList(),
    );
  }
}
