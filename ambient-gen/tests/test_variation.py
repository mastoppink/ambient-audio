import os, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import numpy as np
import config
import form
import settings
from compose import compose, CHORDS, EXTRA_CHORDS, degree_pcs


def test_form_types_in_range_and_deterministic():
    t = np.arange(0, 3600, 7.0)
    for k in form.FORM_TYPES:
        a = form.make_shape(3600, 3, {"type": k, "amount": 0.8})(t)
        b = form.make_shape(3600, 3, {"type": k, "amount": 0.8})(t)
        assert np.array_equal(a, b) and a.min() >= 0 and a.max() <= 1, k
        assert np.abs(np.diff(a)).max() < 0.05, k     # berubah pelan (intro 3 menit paling curam), tanpa lompatan


def test_sections_cover_song_and_first_is_neutral():
    s = form.Sections(3600, 5, 0.7)
    assert s.list[0]["start"] == 0 and s.list[-1]["end"] >= 3600
    assert s.list[0]["register"] == 0 and s.list[0]["melody"] > 0
    m = s.texture_mult(np.arange(0, 3600, 5.0))
    assert np.abs(np.diff(m)).max() < 0.2


def test_extra_chords_only_when_consonant_and_varied():
    for mode in settings.MODES:
        r = settings.resolve(settings.load(overrides=[f"key.mode={mode}", "variation.amount=1"]), 4)
        settings.apply(r)
        used = {e.label.split("(")[0] for e in compose(3600, 4) if e.layer == "pad"}
        for name in used & set(EXTRA_CHORDS):
            pcs = degree_pcs(CHORDS[name][0])
            assert all((a - b) % 12 not in (1, 11) for a in pcs for b in pcs if a != b), (mode, name)


def test_variation_zero_uses_only_original_chords():
    settings.apply(settings.resolve(settings.load(overrides=["variation.amount=0"]), 4))
    config.SECTIONS = None
    used = {e.label.split("(")[0] for e in compose(3600, 4) if e.layer == "pad"}
    assert not used & set(EXTRA_CHORDS)


def test_buat_plans_distinct_videos(tmp_path, monkeypatch):
    import buat
    monkeypatch.setattr(buat, "KATALOG", str(tmp_path / "katalog.json"))
    plan = buat.rencanakan("campur", 3, 20, np.random.default_rng(1), log=lambda *a: None)
    assert len(plan) == 3
    assert len({(v["preset"], v["nada"]) for v in plan}) == 3
    assert all(v["kemiripan_maks"] < 0.75 for v in plan)
