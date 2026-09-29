# -*- coding: utf-8 -*-
"""
REAL audio pipeline: WAV bytes -> prosody feature windows -> SVI input.

No heavyweight DSP deps: pure numpy + stdlib `wave` (PCM WAV). Optional
faster-whisper for server-side ASR (local/on-prem installs; too large for
serverless - that is our graceful-degradation ladder doing its job: browser
ASR or transcript covers it).

Prosody extraction (signal-processing level, no hand-waving):
- RMS energy contour (32ms frames, 16ms hop)
- energy-gated VAD -> silence ratio, avg/longest silence run
- pitch (F0) via autocorrelation per voiced frame (50-400 Hz band)
- pitch_var: coefficient of variation of F0 (monotone vs unstable voice)
- jitter: relative cycle-to-cycle F0 perturbation
- shimmer/tremor proxy: 4-12 Hz amplitude-modulation energy ratio
- speech rate: ASR words/duration when available, else voiced-onset rate
"""
import io
import math
import wave

import numpy as np

TARGET_SR = 16000


class AudioError(Exception):
    pass


def load_wav(raw: bytes):
    """Return (float32 mono signal in [-1,1], sample_rate)."""
    try:
        w = wave.open(io.BytesIO(raw))
    except wave.Error as e:
        raise AudioError("Not a valid PCM WAV file: %s" % e)
    ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), \
        w.getnframes()
    frames = w.readframes(n)
    w.close()
    if sw == 1:
        x = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif sw == 2:
        x = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768
    elif sw == 4:
        x = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648
    else:
        raise AudioError("Unsupported sample width: %d" % sw)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if len(x) < sr // 4:
        raise AudioError("Audio too short (<0.25s)")
    if sr != TARGET_SR:
        t_old = np.arange(len(x)) / sr
        n_new = int(len(x) * TARGET_SR / sr)
        x = np.interp(np.arange(n_new) / TARGET_SR, t_old, x).astype(np.float32)
        sr = TARGET_SR
    return x, sr


def _frames(x, sr, fl=0.032, hop=0.016):
    fl_n, hop_n = int(sr * fl), int(sr * hop)
    n = max(1, 1 + (len(x) - fl_n) // hop_n)
    idx = np.arange(fl_n)[None, :] + hop_n * np.arange(n)[:, None]
    return x[idx], hop_n


def _pitch_track(frames_v, sr):
    """Autocorrelation F0 per voiced frame, 50-400 Hz band."""
    lo, hi = int(sr / 400), int(sr / 50)
    f0s = []
    for fr in frames_v:
        fr = fr - fr.mean()
        if np.sqrt(np.mean(fr ** 2)) < 1e-3:
            continue
        ac = np.correlate(fr, fr, mode="full")[len(fr) - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if seg.size == 0:
            continue
        lag = lo + int(np.argmax(seg))
        if seg[lag - lo] / ac[0] > 0.30:  # periodicity confidence
            f0s.append(sr / lag)
    return np.array(f0s, dtype=np.float32)


def prosody_from_signal(x, sr, duration_s, words=0):
    fl_ms, hop_ms = 0.032, 0.016
    fr, hop_n = _frames(x, sr, fl_ms, hop_ms)
    rms = np.sqrt(np.mean(fr ** 2, axis=1) + 1e-12)
    # noise floor from the LOW-ENERGY frames (10th pct): a median-based floor
    # collapses entirely when speech dominates the window.
    floor = float(np.percentile(rms, 10))
    voiced = rms > max(0.02, 2.2 * floor)

    silence_ratio = float(1.0 - voiced.mean())
    runs, cur = [], 0
    for v in voiced:
        if v:
            if cur:
                runs.append(cur)
            cur = 0
        else:
            cur += 1
    if cur:
        runs.append(cur)
    frame_s = hop_n / sr
    sil_runs = [r * frame_s for r in runs if r * frame_s >= 0.25]
    avg_sil = float(np.mean(sil_runs)) if sil_runs else 0.0

    vf = fr[voiced]
    f0 = _pitch_track(vf[:400], sr)  # cap frames for CPU
    if len(f0) >= 4:
        cv = float(np.std(f0) / max(np.mean(f0), 1e-6))  # monotone ~0.03-0.06
        pitch_var = float(np.clip(cv / 0.28, 0.0, 1.0))
        periods = 1.0 / f0
        jitter = float(np.mean(np.abs(np.diff(periods))) / np.mean(periods)
                       ) if len(f0) > 2 else 0.0
    else:
        pitch_var, jitter = 0.25, 0.0

    # tremor: dominant 4-12 Hz amplitude modulation of the VOICED RMS contour.
    # Peak-to-mean band ratio (noise-normalised) so quiet/noise-only windows
    # do not fake tremor.
    vrms = rms[voiced]
    if len(vrms) > 40:
        contour = vrms - np.mean(vrms)
        spec = np.abs(np.fft.rfft(contour))
        freqs = np.fft.rfftfreq(len(contour), d=frame_s)
        band = spec[(freqs >= 4) & (freqs <= 12)]
        if band.size and band.sum() > 0:
            tremor = float(np.clip(
                ((band.max() / (band.mean() + 1e-9)) - 2.0) / 5.0, 0.0, 1.0))
        else:
            tremor = 0.0
    else:
        tremor = 0.0

    shim_base = rms[voiced]
    shimmer = float(np.mean(np.abs(np.diff(shim_base))) / (np.mean(shim_base)
                    + 1e-9)) if len(shim_base) > 8 else 0.0
    energy_var = float(np.clip(shimmer * 2.2 + min(jitter, 0.05) * 6.0, 0, 1))

    if words and duration_s > 0:
        rate_wps = float(words / duration_s)
    else:
        onsets = int(np.sum(voiced[1:] & ~voiced[:-1]))
        rate_wps = float(np.clip(onsets / max(duration_s, 1e-6) * 0.9, 0, 6))

    return {
        "silence_ratio": round(float(np.clip(silence_ratio, 0, 1)), 3),
        "avg_silence_s": round(avg_sil, 2),
        "pitch_var": round(pitch_var, 3),
        "rate_wps": round(min(rate_wps, 6.0), 2),
        "tremor": round(tremor, 3),
        "energy_var": round(energy_var, 3),
    }


def window_signal(x, sr, win_s=8.0):
    """Split into <=win_s second chunks (last chunk included if >2s)."""
    n = int(win_s * sr)
    chunks, i = [], 0
    while i < len(x):
        c = x[i:i + n]
        if len(c) >= 2 * sr:
            chunks.append(c)
        i += n
    return chunks or [x]


def server_asr_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe_windows(chunks, sr):
    """Server-side ASR (faster-whisper) if installed. Returns list of
    (window_idx, text) or None when ASR is unavailable."""
    if not server_asr_available():
        return None
    from faster_whisper import WhisperModel
    import tempfile, os
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    out = []
    for i, c in enumerate(chunks):
        pcm = (np.clip(c, -1, 1) * 32767).astype(np.int16)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            w = wave.open(f.name, "wb")
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
            w.close()
            segs, _ = model.transcribe(f.name, language=None)
            os.unlink(f.name)
        out.append((i, " ".join(s.text for s in segs).strip()))
    return out
