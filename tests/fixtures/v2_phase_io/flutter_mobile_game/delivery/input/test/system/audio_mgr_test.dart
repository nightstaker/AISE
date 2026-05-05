/// Audio Manager Tests — 音频管理
///
/// Covers:
/// - Initialization guards (StateError when not initialised)
/// - Default volume values
/// - Volume clamping (below 0, above 1)
/// - BGM play / stop / pause / resume / mute
/// - SFX play / stop / mute
/// - stopAll / setAllMuted / reset
/// - isInitialized flag

import 'package:magic_tower/system/audio_mgr.dart';
import 'package:test/test.dart';

void main() {
  group('AudioMgr', () {
    // ────────────────────────────────────────────────────────────────────
    // Initialization
    // ────────────────────────────────────────────────────────────────────

    test('not initialized by default', () {
      final audio = AudioMgr();
      expect(audio.isInitialized, isFalse);
    });

    test('can be initialized', () {
      final audio = AudioMgr();
      expect(audio.isInitialized, isFalse);
      audio.initialize();
      expect(audio.isInitialized, isTrue);
    });

    test('throws StateError when not initialized — setBgmVolume', () {
      final audio = AudioMgr();
      expect(() => audio.setBgmVolume(0.5), throwsStateError);
    });

    test('throws StateError when not initialized — setSfxVolume', () {
      final audio = AudioMgr();
      expect(() => audio.setSfxVolume(0.5), throwsStateError);
    });

    test('throws StateError when not initialized — playBgm', () {
      final audio = AudioMgr();
      expect(() => audio.playBgm('test'), throwsStateError);
    });

    test('throws StateError when not initialized — stopBgm', () {
      final audio = AudioMgr();
      expect(audio.stopBgm, throwsStateError);
    });

    test('throws StateError when not initialized — pauseBgm', () {
      final audio = AudioMgr();
      expect(audio.pauseBgm, throwsStateError);
    });

    test('throws StateError when not initialized — resumeBgm', () {
      final audio = AudioMgr();
      expect(audio.resumeBgm, throwsStateError);
    });

    test('throws StateError when not initialized — setBgmMuted', () {
      final audio = AudioMgr();
      expect(() => audio.setBgmMuted(true), throwsStateError);
    });

    test('throws StateError when not initialized — playSfx', () {
      final audio = AudioMgr();
      expect(() => audio.playSfx('test'), throwsStateError);
    });

    test('throws StateError when not initialized — stopSfx', () {
      final audio = AudioMgr();
      expect(audio.stopSfx, throwsStateError);
    });

    test('throws StateError when not initialized — setSfxMuted', () {
      final audio = AudioMgr();
      expect(() => audio.setSfxMuted(true), throwsStateError);
    });

    test('throws StateError when not initialized — stopAll', () {
      final audio = AudioMgr();
      expect(audio.stopAll, throwsStateError);
    });

    test('throws StateError when not initialized — setAllMuted', () {
      final audio = AudioMgr();
      expect(() => audio.setAllMuted(true), throwsStateError);
    });

    test('throws StateError when not initialized — reset', () {
      final audio = AudioMgr();
      expect(audio.reset, throwsStateError);
    });

    // ────────────────────────────────────────────────────────────────────
    // Default volumes
    // ────────────────────────────────────────────────────────────────────

    test('initial bgm volume is 0.8', () {
      final audio = AudioMgr();
      expect(audio.bgMVolume, 0.8);
    });

    test('initial sfx volume is 1.0', () {
      final audio = AudioMgr();
      expect(audio.sfxVolume, 1.0);
    });

    // ────────────────────────────────────────────────────────────────────
    // Volume control
    // ────────────────────────────────────────────────────────────────────

    test('setBgmVolume clamps below 0 to 0.0', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setBgmVolume(-0.5);
      expect(audio.bgMVolume, 0.0);
    });

    test('setBgmVolume clamps above 1 to 1.0', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setBgmVolume(2.0);
      expect(audio.bgMVolume, 1.0);
    });

    test('setBgmVolume accepts valid range', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setBgmVolume(0.5);
      expect(audio.bgMVolume, 0.5);
    });

    test('setSfxVolume clamps below 0 to 0.0', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setSfxVolume(-0.3);
      expect(audio.sfxVolume, 0.0);
    });

    test('setSfxVolume clamps above 1 to 1.0', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setSfxVolume(5.0);
      expect(audio.sfxVolume, 1.0);
    });

    test('setSfxVolume accepts valid range', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setSfxVolume(0.3);
      expect(audio.sfxVolume, 0.3);
    });

    test('effectiveSfxVolume returns sfxVolume', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setSfxVolume(0.6);
      expect(audio.effectiveSfxVolume, 0.6);
    });

    // ────────────────────────────────────────────────────────────────────
    // BGM playback
    // ────────────────────────────────────────────────────────────────────

    test('playBgm sets track and playing state', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.playBgm('floor1');
      expect(audio.bgmPlaying, isTrue);
      expect(audio.currentBgmTrack, 'floor1');
    });

    test('stopBgm clears track and playing state', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.playBgm('floor1');
      audio.stopBgm();
      expect(audio.bgmPlaying, isFalse);
      expect(audio.currentBgmTrack, isNull);
    });

    test('pauseBgm does nothing when not playing', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.pauseBgm();
      expect(audio.bgmPlaying, isFalse);
    });

    test('pauseBgm when playing does not change bgmPlaying flag (stub)', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.playBgm('floor1');
      audio.pauseBgm();
      // In this stub, pause does not toggle bgmPlaying — it is a
      // no-op placeholder.  In production the flag would be managed
      // by the real audio engine.
      expect(audio.bgmPlaying, isTrue);
    });

    test('resumeBgm does nothing when not playing (stub)', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.resumeBgm();
      expect(audio.bgmPlaying, isFalse);
    });

    test('setBgmMuted sets volume to 0', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setBgmVolume(0.8);
      audio.setBgmMuted(true);
      expect(audio.bgMVolume, 0.0);
    });

    test('setBgmMuted restores volume to 0.8 when unmuted', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setBgmMuted(true);
      audio.setBgmMuted(false);
      expect(audio.bgMVolume, 0.8);
    });

    // ────────────────────────────────────────────────────────────────────
    // SFX playback
    // ────────────────────────────────────────────────────────────────────

    test('playSfx sets track and playing state', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.playSfx('key_open');
      expect(audio.sfxPlaying, isTrue);
      expect(audio.currentSfxTrack, 'key_open');
    });

    test('stopSfx clears track and playing state', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.playSfx('key_open');
      audio.stopSfx();
      expect(audio.sfxPlaying, isFalse);
      expect(audio.currentSfxTrack, isNull);
    });

    test('setSfxMuted sets volume to 0', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setSfxMuted(true);
      expect(audio.sfxVolume, 0.0);
    });

    test('setSfxMuted restores volume to 1.0 when unmuted', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setSfxMuted(true);
      audio.setSfxMuted(false);
      expect(audio.sfxVolume, 1.0);
    });

    // ────────────────────────────────────────────────────────────────────
    // Bulk operations
    // ────────────────────────────────────────────────────────────────────

    test('stopAll stops both BGM and SFX', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.playBgm('floor1');
      audio.playSfx('key_open');
      audio.stopAll();
      expect(audio.bgmPlaying, isFalse);
      expect(audio.sfxPlaying, isFalse);
      expect(audio.currentBgmTrack, isNull);
      expect(audio.currentSfxTrack, isNull);
    });

    test('setAllMuted mutes both channels and stops playback', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.playBgm('floor1');
      audio.playSfx('key_open');
      audio.setAllMuted(true);
      expect(audio.bgMVolume, 0.0);
      expect(audio.sfxVolume, 0.0);
      expect(audio.bgmPlaying, isFalse);
      expect(audio.sfxPlaying, isFalse);
    });

    test('setAllMuted(false) restores volumes', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setAllMuted(true);
      audio.setAllMuted(false);
      expect(audio.bgMVolume, 0.8);
      expect(audio.sfxVolume, 1.0);
    });

    test('reset restores all defaults', () {
      final audio = AudioMgr();
      audio.initialize();
      audio.setBgmVolume(0.0);
      audio.setSfxVolume(0.0);
      audio.playBgm('floor1');
      audio.playSfx('key_open');
      audio.reset();
      expect(audio.bgMVolume, 0.8);
      expect(audio.sfxVolume, 1.0);
      expect(audio.bgmPlaying, isFalse);
      expect(audio.sfxPlaying, isFalse);
      expect(audio.currentBgmTrack, isNull);
      expect(audio.currentSfxTrack, isNull);
    });
  });
}
