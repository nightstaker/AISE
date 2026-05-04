/// Dialogue screen — NPC conversation interface.
///
/// Responsibilities:
/// - Display NPC dialogue text across multiple pages.
/// - Handle scrolling/next-page navigation.
/// - Show NPC portrait (colored rectangle placeholder).

import 'package:flutter/material.dart';

/// Dialogue screen widget — shows NPC conversation text.
class DialogueScreen extends StatefulWidget {
  /// NPC name.
  final String npcName;

  /// Dialogue lines (multiple pages).
  final List<String> dialogueLines;

  /// Current page index (0-based).
  final int currentPage;

  /// Whether the dialogue is still active.
  final bool isActive;

  /// Callback when the player advances to the next page.
  final VoidCallback onNextPage;

  /// Callback to close the dialogue.
  final VoidCallback onClose;

  const DialogueScreen({
    super.key,
    this.npcName = '',
    this.dialogueLines = const [],
    this.currentPage = 0,
    this.isActive = false,
    this.onNextPage = _noop,
    this.onClose = _noop,
  });

  static void _noop() {}

  @override
  State<DialogueScreen> createState() => _DialogueScreenState();

  /// Initialize this screen. Called by the app's lifecycle init.
  void initialize() {
    // DialogueScreen is stateful; initialization handled in initState.
  }

  bool get isInitialized => true;
}

class _DialogueScreenState extends State<DialogueScreen> {
  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black54,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.end,
        children: [
          // NPC portrait placeholder
          Container(
            width: 80,
            height: 80,
            decoration: BoxDecoration(
              color: Colors.purple[300],
              borderRadius: BorderRadius.circular(8),
            ),
            child: Center(
              child: Text(
                widget.npcName.substring(0, 1),
                style: const TextStyle(
                  fontSize: 32,
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
          // NPC name
          Text(
            widget.npcName,
            style: const TextStyle(
              color: Colors.amber,
              fontSize: 16,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          // Dialogue box
          Container(
            width: double.infinity,
            constraints: const BoxConstraints(maxHeight: 200),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.black87,
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(16),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.dialogueLines[widget.currentPage.clamp(0, widget.dialogueLines.length - 1)],
                  style: const TextStyle(color: Colors.white, fontSize: 16),
                ),
                const SizedBox(height: 8),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(
                      onPressed: widget.isActive ? widget.onNextPage : null,
                      child: const Text(
                        '下一句 >>',
                        style: TextStyle(color: Colors.amber),
                      ),
                    ),
                    const SizedBox(width: 16),
                    TextButton(
                      onPressed: widget.onClose,
                      child: const Text(
                        '关闭',
                        style: TextStyle(color: Colors.white70),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
