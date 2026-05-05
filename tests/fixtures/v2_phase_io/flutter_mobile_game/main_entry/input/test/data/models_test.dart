import 'package:magic_tower/data/models.dart';
import 'package:test/test.dart';

// ==================== PlayerState tests ====================

void main() {
  group('PlayerState', () {
    test('default constructor initializes with correct defaults', () {
      final player = PlayerState();

      expect(player.hp, equals(100));
      expect(player.atk, equals(10));
      expect(player.def, equals(10));
      expect(player.gold, equals(0));
      expect(player.exp, equals(0));
      expect(player.level, equals(1));
      expect(player.position, equals(Point(0, 0)));
      expect(player.currentFloor, equals(0));
      expect(player.inventory, isEmpty);
      expect(player.isAlive, isTrue);
    });

    test('constructor with custom values', () {
      final player = PlayerState(
        hp: 50,
        atk: 20,
        def: 15,
        gold: 100,
        exp: 50,
        level: 3,
        position: Point(5, 5),
        currentFloor: 2,
      );

      expect(player.hp, equals(50));
      expect(player.atk, equals(20));
      expect(player.def, equals(15));
      expect(player.gold, equals(100));
      expect(player.exp, equals(50));
      expect(player.level, equals(3));
      expect(player.position, equals(Point(5, 5)));
      expect(player.currentFloor, equals(2));
    });

    test('isAlive returns true when hp > 0', () {
      final player = PlayerState();
      expect(player.isAlive, isTrue);
    });

    test('isAlive returns false when hp <= 0', () {
      final player = PlayerState();
      player.hp = 0;
      expect(player.isAlive, isFalse);
    });

    test('isAlive returns false when hp < 0', () {
      final player = PlayerState();
      player.hp = -10;
      expect(player.isAlive, isFalse);
    });

    test('takeDamage reduces hp', () {
      final player = PlayerState();
      player.takeDamage(20);
      expect(player.hp, equals(80));
    });

    test('takeDamage when hp reaches zero sets isAlive to false', () {
      final player = PlayerState();
      player.takeDamage(100);
      expect(player.isAlive, isFalse);
    });

    test('takeDamage when hp would go negative', () {
      final player = PlayerState();
      player.takeDamage(200);
      expect(player.hp, equals(-100));
      expect(player.isAlive, isFalse);
    });

    test('heal increases hp up to max', () {
      final player = PlayerState();
      player.takeDamage(30);
      player.heal(50);
      expect(player.hp, equals(100));
    });

    test('heal does not exceed max hp', () {
      final player = PlayerState();
      player.heal(50);
      expect(player.hp, equals(100));
    });

    test('heal with no damage', () {
      final player = PlayerState();
      player.heal(10);
      expect(player.hp, equals(100));
    });

    test('addGold increases gold', () {
      final player = PlayerState();
      player.addGold(50);
      expect(player.gold, equals(50));
    });

    test('spendGold reduces gold', () {
      final player = PlayerState();
      player.addGold(100);
      player.spendGold(30);
      expect(player.gold, equals(70));
    });

    test('spendGold when not enough gold throws', () {
      final player = PlayerState();
      expect(() => player.spendGold(50), throwsStateError);
    });

    test('addExp increases exp', () {
      final player = PlayerState();
      player.addExp(100);
      expect(player.exp, equals(100));
    });

    test('move updates position', () {
      final player = PlayerState();
      player.move(3, 4);
      expect(player.position, equals(Point(3, 4)));
    });

    test('move sets current floor', () {
      final player = PlayerState();
      player.moveToFloor(5);
      expect(player.currentFloor, equals(5));
    });

    test('copy creates a deep copy', () {
      final player = PlayerState(
        hp: 50,
        atk: 20,
        def: 15,
        gold: 100,
        exp: 50,
        level: 3,
        position: Point(5, 5),
        currentFloor: 2,
      );
      player.inventory.add(Item(type: ItemType.yellowKey));

      final copy = player.copy();

      expect(copy.hp, equals(player.hp));
      expect(copy.atk, equals(player.atk));
      expect(copy.def, equals(player.def));
      expect(copy.gold, equals(player.gold));
      expect(copy.exp, equals(player.exp));
      expect(copy.level, equals(player.level));
      expect(copy.position, equals(player.position));
      expect(copy.currentFloor, equals(player.currentFloor));
      expect(copy.inventory.length, equals(1));
      expect(copy.inventory.first.type, equals(ItemType.yellowKey));
    });

    test('copy creates independent inventory', () {
      final player = PlayerState();
      player.inventory.add(Item(type: ItemType.redPotion));

      final copy = player.copy();
      copy.inventory.clear();

      expect(player.inventory.length, equals(1));
      expect(copy.inventory, isEmpty);
    });

    test('toMap serializes correctly', () {
      final player = PlayerState(
        hp: 50,
        atk: 20,
        def: 15,
        gold: 100,
        exp: 50,
        level: 3,
        position: Point(5, 5),
        currentFloor: 2,
      );
      player.inventory.add(Item(type: ItemType.yellowKey));

      final map = player.toMap();

      expect(map['hp'], equals(50));
      expect(map['atk'], equals(20));
      expect(map['def'], equals(15));
      expect(map['gold'], equals(100));
      expect(map['exp'], equals(50));
      expect(map['level'], equals(3));
      expect(map['x'], equals(5));
      expect(map['y'], equals(5));
      expect(map['floor'], equals(2));
      expect(map['inventory'], hasLength(1));
    });

    test('fromMap deserializes correctly', () {
      final map = {
        'hp': 75,
        'atk': 25,
        'def': 18,
        'gold': 200,
        'exp': 150,
        'level': 4,
        'x': 6,
        'y': 7,
        'floor': 3,
        'inventory': [
          {'type': 'blueKey', 'count': 1},
        ],
      };

      final player = PlayerState.fromMap(map);

      expect(player.hp, equals(75));
      expect(player.atk, equals(25));
      expect(player.def, equals(18));
      expect(player.gold, equals(200));
      expect(player.exp, equals(150));
      expect(player.level, equals(4));
      expect(player.position, equals(Point(6, 7)));
      expect(player.currentFloor, equals(3));
      expect(player.inventory.length, equals(1));
    });

    test('fromMap with missing inventory defaults to empty', () {
      final map = {
        'hp': 100,
        'atk': 10,
        'def': 10,
        'gold': 0,
        'exp': 0,
        'level': 1,
        'x': 0,
        'y': 0,
        'floor': 0,
      };

      final player = PlayerState.fromMap(map);
      expect(player.inventory, isEmpty);
    });

    test('fromMap with invalid level defaults to 1', () {
      final map = {
        'hp': 100,
        'atk': 10,
        'def': 10,
        'gold': 0,
        'exp': 0,
        'level': -5,
        'x': 0,
        'y': 0,
        'floor': 0,
      };

      final player = PlayerState.fromMap(map);
      expect(player.level, equals(1));
    });

    test('fromMap with invalid hp clamps to 0', () {
      final map = {
        'hp': -50,
        'atk': 10,
        'def': 10,
        'gold': 0,
        'exp': 0,
        'level': 1,
        'x': 0,
        'y': 0,
        'floor': 0,
      };

      final player = PlayerState.fromMap(map);
      expect(player.hp, equals(0));
      expect(player.isAlive, isFalse);
    });
  });

  // ==================== Item tests ====================

  group('Item', () {
    test('creates item with type', () {
      final item = Item(type: ItemType.redPotion);
      expect(item.type, equals(ItemType.redPotion));
      expect(item.count, equals(1));
    });

    test('creates item with type and count', () {
      final item = Item(type: ItemType.yellowKey, count: 3);
      expect(item.type, equals(ItemType.yellowKey));
      expect(item.count, equals(3));
    });

    test('item equality by type and count', () {
      final a = Item(type: ItemType.redPotion, count: 2);
      final b = Item(type: ItemType.redPotion, count: 2);
      final c = Item(type: ItemType.redPotion, count: 3);

      expect(a, equals(b));
      expect(a, isNot(equals(c)));
    });

    test('item hashCode consistent with equals', () {
      final a = Item(type: ItemType.blueKey, count: 1);
      final b = Item(type: ItemType.blueKey, count: 1);
      expect(a.hashCode, equals(b.hashCode));
    });

    test('item toString', () {
      final item = Item(type: ItemType.redGem, count: 5);
      expect(item.toString(), contains('redGem'));
      expect(item.toString(), contains('5'));
    });

    test('toMap serializes correctly', () {
      final item = Item(type: ItemType.blueKey, count: 2);
      final map = item.toMap();
      expect(map['type'], equals('blueKey'));
      expect(map['count'], equals(2));
    });

    test('fromMap deserializes correctly', () {
      final map = {'type': 'redPotion', 'count': 5};
      final item = Item.fromMap(map);
      expect(item.type, equals(ItemType.redPotion));
      expect(item.count, equals(5));
    });
  });

  // ==================== Tile tests ====================

  group('Tile', () {
    test('creates walkable tile', () {
      final tile = Tile(type: TileType.floor, walkable: true);
      expect(tile.type, equals(TileType.floor));
      expect(tile.walkable, isTrue);
    });

    test('creates non-walkable tile', () {
      final tile = Tile(type: TileType.wall, walkable: false);
      expect(tile.type, equals(TileType.wall));
      expect(tile.walkable, isFalse);
    });

    test('walkable defaults to true', () {
      final tile = Tile(type: TileType.floor);
      expect(tile.walkable, isTrue);
    });

    test('wall tile is not walkable by default', () {
      final tile = Tile(type: TileType.wall);
      expect(tile.walkable, isFalse);
    });

    test('door tile is not walkable by default', () {
      final tile = Tile(type: TileType.doorRed);
      expect(tile.walkable, isFalse);
    });

    test('tile equality', () {
      final a = Tile(type: TileType.floor, walkable: true);
      final b = Tile(type: TileType.floor, walkable: true);
      final c = Tile(type: TileType.wall, walkable: false);

      expect(a, equals(b));
      expect(a, isNot(equals(c)));
    });

    test('tile hashCode consistent with equals', () {
      final a = Tile(type: TileType.floor, walkable: true);
      final b = Tile(type: TileType.floor, walkable: true);
      expect(a.hashCode, equals(b.hashCode));
    });

    test('toMap serializes correctly', () {
      final tile = Tile(type: TileType.doorRed, walkable: false);
      final map = tile.toMap();
      expect(map['type'], equals('doorRed'));
      expect(map['walkable'], isFalse);
    });

    test('fromMap deserializes correctly', () {
      final map = {'type': 'stairUp', 'walkable': true};
      final tile = Tile.fromMap(map);
      expect(tile.type, equals(TileType.stairUp));
      expect(tile.walkable, isTrue);
    });
  });

  // ==================== Floor tests ====================

  group('Floor', () {
    test('creates floor with default values', () {
      final floor = Floor(
        level: 0,
        name: 'Entrance',
        width: 11,
        height: 11,
        tiles: [],
      );

      expect(floor.level, equals(0));
      expect(floor.name, equals('Entrance'));
      expect(floor.width, equals(11));
      expect(floor.height, equals(11));
      expect(floor.tiles, isEmpty);
      expect(floor.stairUp, isNull);
      expect(floor.stairDown, isNull);
      expect(floor.requiredKey, isNull);
      expect(floor.bossDefeated, isFalse);
    });

    test('creates floor with all fields', () {
      final floor = Floor(
        level: 5,
        name: 'Dragon Lair',
        width: 11,
        height: 11,
        tiles: [],
        stairUp: Point(5, 10),
        stairDown: Point(5, 0),
        requiredKey: ItemType.redKey,
        bossDefeated: true,
      );

      expect(floor.level, equals(5));
      expect(floor.name, equals('Dragon Lair'));
      expect(floor.width, equals(11));
      expect(floor.height, equals(11));
      expect(floor.stairUp, equals(Point(5, 10)));
      expect(floor.stairDown, equals(Point(5, 0)));
      expect(floor.requiredKey, equals(ItemType.redKey));
      expect(floor.bossDefeated, isTrue);
    });

    test('floor equality by level', () {
      final a = Floor(level: 0, name: 'A', width: 11, height: 11, tiles: []);
      final b = Floor(level: 0, name: 'B', width: 11, height: 11, tiles: []);

      expect(a, equals(b));
    });

    test('floor hashCode consistent with equals', () {
      final a = Floor(level: 1, name: 'A', width: 11, height: 11, tiles: []);
      final b = Floor(level: 1, name: 'B', width: 11, height: 11, tiles: []);
      expect(a.hashCode, equals(b.hashCode));
    });

    test('toMap serializes correctly', () {
      final floor = Floor(
        level: 2,
        name: 'Test Floor',
        width: 11,
        height: 11,
        tiles: [],
        stairUp: Point(3, 4),
        stairDown: Point(7, 6),
        requiredKey: ItemType.blueKey,
        bossDefeated: true,
      );

      final map = floor.toMap();

      expect(map['level'], equals(2));
      expect(map['name'], equals('Test Floor'));
      expect(map['width'], equals(11));
      expect(map['height'], equals(11));
      expect(map['tiles'], hasLength(0));
      expect(map['stairUp'], equals({'x': 3, 'y': 4}));
      expect(map['stairDown'], equals({'x': 7, 'y': 6}));
      expect(map['requiredKey'], equals('blueKey'));
      expect(map['bossDefeated'], isTrue);
    });

    test('fromMap deserializes correctly', () {
      final map = {
        'level': 3,
        'name': 'Deep Floor',
        'width': 11,
        'height': 11,
        'tiles': [],
        'stairUp': {'x': 5, 'y': 5},
        'stairDown': {'x': 5, 'y': 5},
        'requiredKey': 'redKey',
        'bossDefeated': true,
      };

      final floor = Floor.fromMap(map);

      expect(floor.level, equals(3));
      expect(floor.name, equals('Deep Floor'));
      expect(floor.width, equals(11));
      expect(floor.height, equals(11));
      expect(floor.stairUp, equals(Point(5, 5)));
      expect(floor.stairDown, equals(Point(5, 5)));
      expect(floor.requiredKey, equals(ItemType.redKey));
      expect(floor.bossDefeated, isTrue);
    });

    test('fromMap with null stairs', () {
      final map = {
        'level': 0,
        'name': 'Start',
        'width': 11,
        'height': 11,
        'tiles': [],
        'stairUp': null,
        'stairDown': null,
        'requiredKey': null,
        'bossDefeated': false,
      };

      final floor = Floor.fromMap(map);
      expect(floor.stairUp, isNull);
      expect(floor.stairDown, isNull);
      expect(floor.requiredKey, isNull);
      expect(floor.bossDefeated, isFalse);
    });
  });

  // ==================== Point tests ====================

  group('Point', () {
    test('creates point with x and y', () {
      final point = Point(3, 4);
      expect(point.x, equals(3));
      expect(point.y, equals(4));
    });

    test('point equality', () {
      final a = Point(1, 2);
      final b = Point(1, 2);
      final c = Point(2, 1);

      expect(a, equals(b));
      expect(a, isNot(equals(c)));
    });

    test('point hashCode consistent with equals', () {
      final a = Point(5, 6);
      final b = Point(5, 6);
      expect(a.hashCode, equals(b.hashCode));
    });

    test('point toString', () {
      final point = Point(7, 8);
      expect(point.toString(), contains('7'));
      expect(point.toString(), contains('8'));
    });

    test('distance to another point', () {
      final a = Point(0, 0);
      final b = Point(3, 4);
      expect(a.distanceTo(b), equals(5));
    });

    test('distance to same point is zero', () {
      final a = Point(5, 5);
      expect(a.distanceTo(a), equals(0));
    });

    test('isAdjacent returns true for adjacent tiles', () {
      final a = Point(5, 5);
      expect(a.isAdjacent(Point(4, 5)), isTrue);
      expect(a.isAdjacent(Point(6, 5)), isTrue);
      expect(a.isAdjacent(Point(5, 4)), isTrue);
      expect(a.isAdjacent(Point(5, 6)), isTrue);
    });

    test('isAdjacent returns false for non-adjacent tiles', () {
      final a = Point(5, 5);
      expect(a.isAdjacent(Point(3, 5)), isFalse);
      expect(a.isAdjacent(Point(5, 3)), isFalse);
      expect(a.isAdjacent(Point(4, 4)), isFalse);
    });

    test('offset returns new point', () {
      final a = Point(2, 3);
      final b = a.offset(dx: 1, dy: -1);
      expect(b.x, equals(3));
      expect(b.y, equals(2));
    });

    test('directionTo returns correct direction', () {
      final a = Point(5, 5);
      final b = Point(5, 6);
      expect(a.directionTo(b), equals(Dir.down));
    });

    test('directionTo returns correct direction for left', () {
      final a = Point(5, 5);
      final b = Point(4, 5);
      expect(a.directionTo(b), equals(Dir.left));
    });

    test('directionTo returns null for same point', () {
      final a = Point(5, 5);
      expect(a.directionTo(a), isNull);
    });
  });

  // ==================== Direction tests ====================

  group('Dir', () {
    test('directionToUp returns correct offset', () {
      final offset = Dir.up.offset;
      expect(offset.dx, equals(0));
      expect(offset.dy, equals(-1));
    });

    test('directionToDown returns correct offset', () {
      final offset = Dir.down.offset;
      expect(offset.dx, equals(0));
      expect(offset.dy, equals(1));
    });

    test('directionToLeft returns correct offset', () {
      final offset = Dir.left.offset;
      expect(offset.dx, equals(-1));
      expect(offset.dy, equals(0));
    });

    test('directionToRight returns correct offset', () {
      final offset = Dir.right.offset;
      expect(offset.dx, equals(1));
      expect(offset.dy, equals(0));
    });

    test('opposite returns correct opposite direction', () {
      expect(Dir.up.opposite, equals(Dir.down));
      expect(Dir.down.opposite, equals(Dir.up));
      expect(Dir.left.opposite, equals(Dir.right));
      expect(Dir.right.opposite, equals(Dir.left));
    });

    test('toString returns direction name', () {
      expect(Dir.up.toString(), equals('up'));
      expect(Dir.down.toString(), equals('down'));
      expect(Dir.left.toString(), equals('left'));
      expect(Dir.right.toString(), equals('right'));
    });
  });

  // ==================== BattleResult tests ====================

  group('BattleResult', () {
    test('creates battle result with player win', () {
      final result = BattleResult(
        winner: BattleWinner.player,
        playerDamageTaken: 20,
        monsterDamageDealt: 30,
        rounds: 5,
        goldEarned: 50,
        expEarned: 100,
      );

      expect(result.winner, equals(BattleWinner.player));
      expect(result.playerDamageTaken, equals(20));
      expect(result.monsterDamageDealt, equals(30));
      expect(result.rounds, equals(5));
      expect(result.goldEarned, equals(50));
      expect(result.expEarned, equals(100));
      expect(result.isPlayerWin, isTrue);
      expect(result.isPlayerDead, isFalse);
    });

    test('creates battle result with player loss', () {
      final result = BattleResult(
        winner: BattleWinner.monster,
        playerDamageTaken: 100,
        monsterDamageDealt: 10,
        rounds: 3,
        goldEarned: 0,
        expEarned: 0,
      );

      expect(result.winner, equals(BattleWinner.monster));
      expect(result.isPlayerWin, isFalse);
      expect(result.isPlayerDead, isTrue);
    });

    test('isPlayerWin reflects winner', () {
      final win = BattleResult(
        winner: BattleWinner.player,
        playerDamageTaken: 0,
        monsterDamageDealt: 0,
        rounds: 0,
        goldEarned: 0,
        expEarned: 0,
      );
      expect(win.isPlayerWin, isTrue);

      final loss = BattleResult(
        winner: BattleWinner.monster,
        playerDamageTaken: 0,
        monsterDamageDealt: 0,
        rounds: 0,
        goldEarned: 0,
        expEarned: 0,
      );
      expect(loss.isPlayerWin, isFalse);
    });

    test('isPlayerDead reflects winner', () {
      final win = BattleResult(
        winner: BattleWinner.player,
        playerDamageTaken: 0,
        monsterDamageDealt: 0,
        rounds: 0,
        goldEarned: 0,
        expEarned: 0,
      );
      expect(win.isPlayerDead, isFalse);

      final loss = BattleResult(
        winner: BattleWinner.monster,
        playerDamageTaken: 0,
        monsterDamageDealt: 0,
        rounds: 0,
        goldEarned: 0,
        expEarned: 0,
      );
      expect(loss.isPlayerDead, isTrue);
    });

    test('toMap serializes correctly', () {
      final result = BattleResult(
        winner: BattleWinner.player,
        playerDamageTaken: 25,
        monsterDamageDealt: 15,
        rounds: 4,
        goldEarned: 30,
        expEarned: 60,
      );

      final map = result.toMap();

      expect(map['winner'], equals('player'));
      expect(map['playerDamageTaken'], equals(25));
      expect(map['monsterDamageDealt'], equals(15));
      expect(map['rounds'], equals(4));
      expect(map['goldEarned'], equals(30));
      expect(map['expEarned'], equals(60));
    });

    test('fromMap deserializes correctly', () {
      final map = {
        'winner': 'player',
        'playerDamageTaken': 30,
        'monsterDamageDealt': 20,
        'rounds': 6,
        'goldEarned': 40,
        'expEarned': 80,
      };

      final result = BattleResult.fromMap(map);

      expect(result.winner, equals(BattleWinner.player));
      expect(result.playerDamageTaken, equals(30));
      expect(result.monsterDamageDealt, equals(20));
      expect(result.rounds, equals(6));
      expect(result.goldEarned, equals(40));
      expect(result.expEarned, equals(80));
    });
  });

  // ==================== GameState tests ====================

  group('GameState', () {
    test('creates game state with defaults', () {
      final state = GameState();

      expect(state.player, isNotNull);
      expect(state.floors, isEmpty);
      expect(state.currentFloorIndex, equals(0));
      expect(state.isBattleActive, isFalse);
      expect(state.isInShop, isFalse);
      expect(state.isInDialogue, isFalse);
      expect(state.dialogueText, isEmpty);
      expect(state.battleResult, isNull);
      expect(state.npcMessages, isEmpty);
      expect(state.isGameOver, isFalse);
      expect(state.isPaused, isFalse);
    });

    test('sets current floor', () {
      final state = GameState();
      final floor = Floor(level: 1, name: 'Floor 1', width: 11, height: 11, tiles: []);
      state.floors.add(floor);

      state.setCurrentFloor(1);
      expect(state.currentFloorIndex, equals(1));
    });

    test('setBattleActive toggles battle state', () {
      final state = GameState();

      state.setBattleActive(true);
      expect(state.isBattleActive, isTrue);

      state.setBattleActive(false);
      expect(state.isBattleActive, isFalse);
    });

    test('setShopActive toggles shop state', () {
      final state = GameState();

      state.setShopActive(true);
      expect(state.isInShop, isTrue);

      state.setShopActive(false);
      expect(state.isInShop, isFalse);
    });

    test('setDialogueActive toggles dialogue state', () {
      final state = GameState();

      state.setDialogueActive(true, 'Hello world');
      expect(state.isInDialogue, isTrue);
      expect(state.dialogueText, equals('Hello world'));

      state.setDialogueActive(false, '');
      expect(state.isInDialogue, isFalse);
    });

    test('setBattleResult stores battle result', () {
      final state = GameState();
      final result = BattleResult(
        winner: BattleWinner.player,
        playerDamageTaken: 10,
        monsterDamageDealt: 5,
        rounds: 2,
        goldEarned: 20,
        expEarned: 40,
      );

      state.setBattleResult(result);
      expect(state.battleResult, equals(result));
    });

    test('setGameOver toggles game over', () {
      final state = GameState();

      state.setGameOver(true);
      expect(state.isGameOver, isTrue);

      state.setGameOver(false);
      expect(state.isGameOver, isFalse);
    });

    test('setPaused toggles pause', () {
      final state = GameState();

      state.setPaused(true);
      expect(state.isPaused, isTrue);

      state.setPaused(false);
      expect(state.isPaused, isFalse);
    });

    test('addNpcMessage adds message', () {
      final state = GameState();
      state.addNpcMessage('Welcome to the tower!');

      expect(state.npcMessages.length, equals(1));
      expect(state.npcMessages.first, equals('Welcome to the tower!'));
    });

    test('clearNpcMessages clears all messages', () {
      final state = GameState();
      state.addNpcMessage('Message 1');
      state.addNpcMessage('Message 2');

      state.clearNpcMessages();
      expect(state.npcMessages, isEmpty);
    });

    test('copy creates a copy', () {
      final state = GameState();
      final copy = state.copy();

      expect(copy.currentFloorIndex, equals(state.currentFloorIndex));
      expect(copy.isBattleActive, equals(state.isBattleActive));
      expect(copy.isInShop, equals(state.isInShop));
      expect(copy.isInDialogue, equals(state.isInDialogue));
      expect(copy.isGameOver, equals(state.isGameOver));
      expect(copy.isPaused, equals(state.isPaused));
    });

    test('toMap serializes correctly', () {
      final state = GameState();
      final floor = Floor(level: 0, name: 'Start', width: 11, height: 11, tiles: []);
      state.floors.add(floor);

      final map = state.toMap();

      expect(map['currentFloorIndex'], equals(0));
      expect(map['isBattleActive'], isFalse);
      expect(map['isInShop'], isFalse);
      expect(map['isInDialogue'], isFalse);
      expect(map['isGameOver'], isFalse);
      expect(map['isPaused'], isFalse);
      expect(map['dialogueText'], isEmpty);
      expect(map['floors'], hasLength(1));
    });

    test('fromMap deserializes correctly', () {
      final map = {
        'currentFloorIndex': 2,
        'isBattleActive': true,
        'isInShop': false,
        'isInDialogue': false,
        'isGameOver': false,
        'isPaused': false,
        'dialogueText': 'Test dialogue',
        'floors': [],
        'npcMessages': ['Hello'],
      };

      final state = GameState.fromMap(map);

      expect(state.currentFloorIndex, equals(2));
      expect(state.isBattleActive, isTrue);
      expect(state.isInShop, isFalse);
      expect(state.isInDialogue, isFalse);
      expect(state.isGameOver, isFalse);
      expect(state.isPaused, isFalse);
      expect(state.dialogueText, equals('Test dialogue'));
      expect(state.npcMessages, hasLength(1));
    });
  });

  // ==================== SaveData tests ====================

  group('SaveData', () {
    test('creates save data with defaults', () {
      final save = SaveData();

      expect(save.version, equals('1.0.0'));
      expect(save.timestamp, isNotNull);
      expect(save.gameState, isNotNull);
    });

    test('toMap serializes correctly', () {
      final save = SaveData();
      final map = save.toMap();

      expect(map['version'], equals('1.0.0'));
      expect(map['timestamp'], isNotNull);
      expect(map['gameState'], isNotNull);
    });

    test('fromMap deserializes correctly', () {
      final map = {
        'version': '1.0.0',
        'timestamp': 1234567890,
        'gameState': {
          'currentFloorIndex': 1,
          'isBattleActive': false,
          'isInShop': false,
          'isInDialogue': false,
          'isGameOver': false,
          'isPaused': false,
          'dialogueText': '',
          'floors': [],
          'npcMessages': [],
        },
      };

      final save = SaveData.fromMap(map);

      expect(save.version, equals('1.0.0'));
      expect(save.timestamp, equals(1234567890));
      expect(save.gameState.currentFloorIndex, equals(1));
    });
  });
}
