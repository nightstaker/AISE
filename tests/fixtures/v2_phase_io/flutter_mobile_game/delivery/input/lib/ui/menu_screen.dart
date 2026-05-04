/// Menu screen — splash + main menu (start / continue / settings / about)
///
/// This is the first screen the player sees after the splash. It provides
/// navigation to every other subsystem: gameplay, settings, and continue.

import 'package:flutter/material.dart';

/// Menu screen state — which menu item the player is on.
enum MenuAction {
  start,
  continueGame,
  settings,
  about,
}

/// Menu screen widget.
///
/// Responsibilities:
/// - Show splash on first frame, then main menu.
/// - Provide buttons for: New Game, Continue, Settings, About.
/// - Signal navigation callbacks to the parent app.
class MenuScreen extends StatefulWidget {
  /// Callback fired when "New Game" is pressed.
  final VoidCallback onNewGame;

  /// Callback fired when "Continue" is pressed.
  final VoidCallback onContinue;

  /// Callback fired when "Settings" is pressed.
  final VoidCallback onSettings;

  /// Callback fired when "About" is pressed.
  final VoidCallback onAbout;

  const MenuScreen({
    super.key,
    this.onNewGame = _noop,
    this.onContinue = _noop,
    this.onSettings = _noop,
    this.onAbout = _noop,
  });

  static void _noop() {}

  @override
  State<MenuScreen> createState() => _MenuScreenState();
}

class _MenuScreenState extends State<MenuScreen> {
  /// Whether the splash is still showing.
  bool _showingSplash = true;

  /// Splash duration in milliseconds.
  static const int _splashDurationMs = 2000;

  @override
  void initState() {
    super.initState();
    // After splash duration, transition to main menu.
    Future.delayed(
      const Duration(milliseconds: _splashDurationMs),
      () => setState(() => _showingSplash = false),
    );
  }

  /// Initialize this screen. Called by the app's lifecycle init.
  void initialize() {
    // MenuScreen is stateful; initialization is handled in initState.
  }

  bool get isInitialized => true;

  @override
  Widget build(BuildContext context) {
    if (_showingSplash) {
      return _buildSplash(context);
    }
    return _buildMainMenu(context);
  }

  Widget _buildSplash(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Title placeholder — a colored rectangle.
            Container(
              width: 200,
              height: 200,
              decoration: BoxDecoration(
                color: Colors.amber,
                borderRadius: BorderRadius.circular(16),
              ),
              child: const Center(
                child: Text(
                  '魔塔',
                  style: TextStyle(
                    fontSize: 48,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 24),
            const Text(
              'Magic Tower',
              style: TextStyle(
                fontSize: 24,
                color: Colors.white70,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMainMenu(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: Colors.grey[900],
      body: Center(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Title
                Container(
                  width: 160,
                  height: 160,
                  decoration: BoxDecoration(
                    color: Colors.amber,
                    borderRadius: BorderRadius.circular(16),
                  ),
                ),
                const SizedBox(height: 32),
                Text(
                  '魔塔',
                  style: theme.textTheme.displayLarge?.copyWith(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Magic Tower',
                  style: theme.textTheme.headlineSmall?.copyWith(
                    color: Colors.white70,
                  ),
                ),
                const SizedBox(height: 48),
                // Menu buttons
                _buildMenuButton(
                  context,
                  label: '开始游戏',
                  sublabel: 'New Game',
                  onPressed: widget.onNewGame,
                ),
                const SizedBox(height: 16),
                _buildMenuButton(
                  context,
                  label: '继续游戏',
                  sublabel: 'Continue',
                  onPressed: widget.onContinue,
                ),
                const SizedBox(height: 16),
                _buildMenuButton(
                  context,
                  label: '设置',
                  sublabel: 'Settings',
                  onPressed: widget.onSettings,
                ),
                const SizedBox(height: 16),
                _buildMenuButton(
                  context,
                  label: '关于',
                  sublabel: 'About',
                  onPressed: widget.onAbout,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildMenuButton(
    BuildContext context, {
    required String label,
    required String sublabel,
    required VoidCallback onPressed,
  }) {
    final theme = Theme.of(context);
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: Colors.amber[700],
          padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
        child: Column(
          children: [
            Text(
              label,
              style: theme.textTheme.titleLarge?.copyWith(
                color: Colors.white,
                fontWeight: FontWeight.bold,
              ),
            ),
            Text(
              sublabel,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: Colors.white70,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
