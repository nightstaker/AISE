/// Audio Manager — BGM/SFX volume control + playback placeholders.
///
/// Manages independent volume levels for background music (BGM) and
/// sound effects (SFX).  Provides stub methods for play/stop/pause
/// so that UI code can call them without null-checks; in production
/// these would wire to a real audio engine.

class AudioMgr {
  AudioMgr();

  bool _initialized = false;

  /// BGM volume: 0.0 (silent) – 1.0 (max).
  double bgMVolume = 0.8;

  /// SFX volume: 0.0 (silent) – 1.0 (max).
  double sfxVolume = 1.0;

  /// Whether any BGM is currently playing.
  bool bgmPlaying = false;

  /// Whether any SFX is currently playing.
  bool sfxPlaying = false;

  /// Current BGM track identifier (e.g. `'floor1'`).
  String? currentBgmTrack;

  /// Current SFX track identifier (e.g. `'sword_hit'`).
  String? currentSfxTrack;

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------

  /// Initialize the audio subsystem.  Must be called before any
  /// playback or volume methods; otherwise [StateError] is thrown.
  void initialize() {
    _initialized = true;
  }

  bool get isInitialized => _initialized;

  // ------------------------------------------------------------------
  // Volume control
  // ------------------------------------------------------------------

  /// Set BGM volume.  Clamped to [0.0, 1.0].
  void setBgmVolume(double volume) {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    bgMVolume = volume.clamp(0.0, 1.0);
  }

  /// Set SFX volume.  Clamped to [0.0, 1.0].
  void setSfxVolume(double volume) {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    sfxVolume = volume.clamp(0.0, 1.0);
  }

  /// Get the effective SFX volume (convenience alias).
  double get effectiveSfxVolume => sfxVolume;

  // ------------------------------------------------------------------
  // BGM playback placeholders
  // ------------------------------------------------------------------

  /// Play a BGM track.  [trackId] is an asset path or identifier
  /// such as `'assets/audio/bgm_floor1.ogg'`.
  void playBgm(String trackId) {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    bgmPlaying = true;
    currentBgmTrack = trackId;
    // TODO: wire to real audio player with bgMVolume
  }

  /// Stop the currently playing BGM.
  void stopBgm() {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    bgmPlaying = false;
    currentBgmTrack = null;
    // TODO: stop real audio player
  }

  /// Pause the currently playing BGM.
  void pauseBgm() {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    if (!bgmPlaying) return;
    // TODO: pause real audio player
  }

  /// Resume a paused BGM.
  void resumeBgm() {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    if (!bgmPlaying) return;
    // TODO: resume real audio player
  }

  /// Mute or unmute BGM.
  void setBgmMuted(bool muted) {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    if (muted) {
      bgMVolume = 0.0;
    } else {
      bgMVolume = 0.8;
    }
  }

  // ------------------------------------------------------------------
  // SFX playback placeholders
  // ------------------------------------------------------------------

  /// Play a one-shot SFX.  [trackId] is an asset path or identifier
  /// such as `'assets/audio/sfx_key_open.wav'`.
  void playSfx(String trackId) {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    sfxPlaying = true;
    currentSfxTrack = trackId;
    // TODO: wire to real audio player with sfxVolume
  }

  /// Stop the currently playing SFX.
  void stopSfx() {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    sfxPlaying = false;
    currentSfxTrack = null;
    // TODO: stop real audio player
  }

  /// Mute or unmute SFX.
  void setSfxMuted(bool muted) {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    if (muted) {
      sfxVolume = 0.0;
    } else {
      sfxVolume = 1.0;
    }
  }

  // ------------------------------------------------------------------
  // Bulk operations
  // ------------------------------------------------------------------

  /// Stop all audio (BGM + SFX).
  void stopAll() {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    stopBgm();
    stopSfx();
  }

  /// Mute or unmute everything.
  void setAllMuted(bool muted) {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    bgMVolume = muted ? 0.0 : 0.8;
    sfxVolume = muted ? 0.0 : 1.0;
    if (muted) stopAll();
  }

  /// Reset all audio settings to factory defaults.
  void reset() {
    if (!_initialized) throw StateError('AudioMgr not initialized');
    bgMVolume = 0.8;
    sfxVolume = 1.0;
    bgmPlaying = false;
    sfxPlaying = false;
    currentBgmTrack = null;
    currentSfxTrack = null;
  }
}
