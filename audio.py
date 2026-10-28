"""Audio finishing in pure Python (no ffmpeg), so the app runs the same on Windows and Linux.

    finish(audio, sr)    -> 48 kHz float32 at -16 LUFS, peaks held under -1.5 dBFS
    prepare_reference()  -> a clean 10-15 s clip of speech for voice cloning
"""
import math

import numpy as np
import pyloudnorm
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import resample_poly

OUT_SR = 48000
TARGET_LUFS = -16.0
CEILING = 10 ** (-1.5 / 20)  # -1.5 dBFS


def to_mono(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    return audio.mean(axis=1) if audio.ndim == 2 else audio


def resample(audio: np.ndarray, sr: int, target: int) -> np.ndarray:
    if sr == target:
        return audio.astype(np.float32)
    g = math.gcd(sr, target)
    return resample_poly(audio, target // g, sr // g).astype(np.float32)


def loudness(audio: np.ndarray, sr: int) -> float:
    """Integrated loudness, EBU R128 / ITU-R BS.1770 (the measure ffmpeg's ebur128 reports)."""
    if len(audio) < int(0.4 * sr):  # the meter needs at least one 400 ms block
        audio = np.pad(audio, (0, int(0.4 * sr) - len(audio)))
    return float(pyloudnorm.Meter(sr).integrated_loudness(audio))


def limit(audio: np.ndarray, sr: int, ceiling: float = CEILING) -> np.ndarray:
    """Peak limiter: 2 ms lookahead, gain falls instantly before a peak and recovers over ~60 ms.
    Measured on a 4x oversampled copy, so peaks between samples are caught too."""
    over = np.abs(resample_poly(audio, 4, 1)).reshape(-1, 4).max(axis=1)[: len(audio)]
    over = np.pad(over, (0, len(audio) - len(over)))
    need = np.minimum(1.0, ceiling / np.maximum(over, 1e-9))
    look = max(1, int(0.002 * sr))
    gain = -maximum_filter1d(-need, size=2 * look + 1)  # running minimum: dip before the peak arrives
    gain = np.minimum(gain, uniform_filter1d(gain, size=max(1, int(0.06 * sr))))  # smooth the release
    out = audio * gain
    return np.clip(out, -ceiling, ceiling).astype(np.float32)


def finish(audio: np.ndarray, sr: int) -> np.ndarray:
    """Mono, 48 kHz, one fixed gain to -16 LUFS, then the limiter. Refuses near-silence, which a
    gain to -16 LUFS would only turn into loud hiss."""
    audio = resample(to_mono(audio), sr, OUT_SR)
    level = loudness(audio, OUT_SR)
    if not math.isfinite(level) or level < -50:
        raise RuntimeError('o modelo devolveu silêncio; tente reescrever o texto')
    gain = 10 ** (min(TARGET_LUFS - level, 30) / 20)
    return limit(audio * gain, OUT_SR)


def prepare_reference(audio: np.ndarray, sr: int, seconds: float = 12.0, out_sr: int = 24000) -> tuple[np.ndarray, float]:
    """From a recording of someone reading: drop the silences, keep the `seconds`-long stretch with
    the most speech, normalize it to -20 LUFS. Returns (clip, seconds of speech found)."""
    audio = resample(to_mono(audio), sr, out_sr)
    win = int(0.05 * out_sr)
    n = len(audio) // win
    if n == 0:
        raise ValueError('gravação curta demais')
    frames = audio[: n * win].reshape(n, win)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    # Speech: frames well above the recording's own noise floor.
    floor = np.percentile(db, 10)
    voiced = db > max(floor + 15, -55)
    speech_s = voiced.sum() * 0.05
    if speech_s < 4:
        raise ValueError(f'só achei {speech_s:.0f} s de fala; grave pelo menos uns 10 s lendo o texto')
    # Keep voiced frames plus a little air around them, so words aren't clipped.
    keep = maximum_filter1d(voiced.astype(np.uint8), size=7).astype(bool)
    speech = frames[keep].reshape(-1)
    want = int(seconds * out_sr)
    if len(speech) > want:
        # The window with the most energy: the steadiest, most confident stretch of reading.
        energy = np.convolve(speech ** 2, np.ones(win, dtype=np.float32), 'valid')[::win]
        span = want // win
        best = int(np.argmax(np.convolve(energy, np.ones(span), 'valid'))) * win
        speech = speech[best: best + want]
    level = loudness(speech, out_sr)
    if math.isfinite(level):
        speech = speech * 10 ** ((-20 - level) / 20)
    fade = int(0.02 * out_sr)
    ramp = np.linspace(0, 1, fade, dtype=np.float32)
    speech[:fade] *= ramp
    speech[-fade:] *= ramp[::-1]
    return np.clip(speech, -0.99, 0.99).astype(np.float32), round(speech_s, 1)
