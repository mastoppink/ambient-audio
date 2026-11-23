import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
import config
from compose import compose, voice_lead


def test_events_in_scale_and_range():
    ev = compose(300, np.random.default_rng(3))
    scale_pcs = {(config.TONIC_MIDI + s) % 12 for s in config.SCALE}
    lo, hi = config.PAD_RANGE
    for e in ev:
        assert e.midi % 12 in scale_pcs
        assert e.start + e.dur <= 300 + 1e-6
        if e.layer == "pad":
            assert lo <= e.midi <= hi


def test_voice_leading_moves_little():
    a = voice_lead([], [2, 6, 9, 4], 52, 74)
    b = voice_lead(a, [4, 8, 11, 2], 52, 74)
    assert max(min(abs(x - y) for y in a) for x in b) <= 3


def test_chords_overlap_for_crossfade():
    ev = compose(300, np.random.default_rng(3))
    starts = sorted({e.start for e in ev if e.layer == "pad"})
    ends = {e.start: e.start + e.dur for e in ev if e.layer == "pad"}
    for s0, s1 in zip(starts, starts[1:]):
        assert ends[s0] > s1
