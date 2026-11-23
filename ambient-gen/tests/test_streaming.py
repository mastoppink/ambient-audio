import numpy as np
import config
import fx
from compose import compose
from render import render_segment

SR = config.SAMPLE_RATE


def test_segments_equal_whole_render():
    total = 40.0
    ev = compose(total, 4, with_melody=True)
    n = int(total * SR)
    whole = render_segment(ev, 0, n, 4)
    seg = int(7.3 * SR)   # batas segmen sengaja tidak rapi
    parts = [render_segment(ev, s, min(seg, n - s), 4, i) for i, s in enumerate(range(0, n, seg))]
    for k in ("drone", "pad", "melody"):
        joined = np.vstack([p[k] for p in parts])
        assert np.abs(joined - whole[k]).max() < 1e-5, k


def test_stream_reverb_equals_batch():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((SR * 6, 2))
    ir = fx.make_ir(2.0, 0.01, np.random.default_rng(1))
    batch = fx.reverb(x, ir)
    r = fx.StreamReverb(ir)
    stream = np.vstack([r(x[i:i + SR // 2]) for i in range(0, len(x), SR // 2)])  # potongan < IR
    assert np.abs(stream - batch).max() < 1e-9


def test_stream_limiter_matches_batch_and_ceiling():
    rng = np.random.default_rng(2)
    x = rng.standard_normal((SR * 3, 2)) * np.linspace(0.05, 1.5, SR * 3)[:, None]
    batch = fx.limiter(x, -1.0)
    lim = fx.StreamLimiter(-1.0)
    out = [lim.push(x[i:i + 12345]) for i in range(0, len(x), 12345)] + [lim.flush()]
    stream = np.vstack(out)
    assert stream.shape == x.shape
    assert np.abs(stream).max() <= 10 ** (-1 / 20) + 1e-9
    assert np.abs(stream - batch).max() < 0.05


def test_loudness_meter_matches_pyloudnorm():
    import pyloudnorm as pyln
    from loudness import LoudnessMeter
    x = np.random.default_rng(0).standard_normal((SR * 20, 2)) * 0.1
    m = LoudnessMeter()
    for i in range(0, len(x), 77777):
        m.add(x[i:i + 77777])
    assert abs(m.integrated() - pyln.Meter(SR).integrated_loudness(x)) < 0.1


def test_preview_audio_is_prefix_of_long_with_form():
    import settings
    from form import make_shape
    r = settings.resolve(settings.load(), 11)
    settings.apply(r)
    config.SHAPE = make_shape(1800, 11, r["form"])      # kurva dari durasi penuh
    short = render_segment(compose(60, 11, with_melody=True), 0, 40 * SR, 11)
    long_ = render_segment(compose(1800, 11, with_melody=True), 0, 40 * SR, 11)
    for k in ("pad", "melody", "texture"):
        assert np.abs(short[k] - long_[k]).max() < 1e-5, k


def test_segments_equal_whole_with_timbres_and_phrases():
    import settings
    for tb in ("glass", "kalimba", "piano"):
        settings.apply(settings.resolve(settings.load(
            overrides=[f'melody.timbre="{tb}"', "melody.phrases=0.8", "melody.density=1.0"]), 5))
        ev = [e for e in compose(60, 5, with_melody=True) if e.layer == "melody"]  # hanya melodi: cepat
        assert len(ev) >= 3
        n = 60 * SR
        whole = render_segment(ev, 0, n, 5)["melody"]
        seg = int(11.7 * SR)
        parts = np.vstack([render_segment(ev, s, min(seg, n - s), 5, i)["melody"]
                           for i, s in enumerate(range(0, n, seg))])
        assert np.abs(parts - whole).max() < 1e-5, tb
