import numpy as np
import synth
from synth import melody_voice

SR = 48000


def _note(midi, dur=10, vel=0.8, seed=3):
    return synth._piano_note(midi, synth.midi_to_hz(midi), int(dur * SR), 9.0, vel, seed)


def _level_at(y, sec):
    e = np.convolve(y ** 2, np.ones(2400) / 2400, mode="same")
    return 10 * np.log10(e[int(sec * SR)] / e.max())


def test_partials_are_stretched_like_a_real_piano():
    x = _note(48)[int(0.05 * SR):int(1.05 * SR)]
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)))); f = np.fft.rfftfreq(len(x), 1 / SR)
    f0 = synth.midi_to_hz(48)
    band = (f > f0 * 10 - 20) & (f < f0 * 10 + 40)
    peak = f[band][np.argmax(X[band])]
    assert peak > f0 * 10 * 2 ** (5 / 1200)           # parsial ke-10 lebih tinggi > 5 cent


def test_low_notes_ring_longer_than_high_notes():
    assert _level_at(_note(48, 25), 12) > _level_at(_note(84, 25), 12) + 10


def test_harder_notes_are_brighter():
    def hi(v):
        y = _note(60, 2, vel=v)[:SR]; Y = np.abs(np.fft.rfft(y)) ** 2; f = np.fft.rfftfreq(len(y), 1 / SR)
        return Y[f > 1500].sum() / Y.sum()
    assert hi(1.0) > 4 * hi(0.3)


def test_piano_segments_identical():
    a = melody_voice("piano", 60, 20, np.random.default_rng(5), 9, 0.5)
    b = np.vstack([melody_voice("piano", 60, 20, np.random.default_rng(5), 9, 0.5, offset=o, n=min(77777, 20 * SR - o))
                   for o in range(0, 20 * SR, 77777)])
    assert np.abs(a - b).max() < 1e-9
