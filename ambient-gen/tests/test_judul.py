import os, pathlib
os.chdir(pathlib.Path(__file__).resolve().parents[1])
import config
import form
import judul
import settings


def _r(preset, seed, menit=60):
    r = settings.resolve(settings.load(f"presets/{preset}.toml"), seed)
    r["duration_min"] = menit
    settings.apply(r)
    secs = form.Sections(menit * 60, seed, config.VARIATION, r["mix"]["melody"] > 0) if config.VARIATION > 0 else None
    return r, secs


PRESETS = [p.stem for p in pathlib.Path("presets").glob("*.toml")]


def test_titles_honest_short_and_varied():
    for p in PRESETS:
        for seed in (1, 2, 3):
            r, secs = _r(p, seed)
            h = judul.buat(r, sections=secs)
            for t in h["judul_en"] + h["judul_id"]:
                assert len(t) <= 100, t
                assert all(w not in t.lower() for w in judul.KATA["terlarang"]), t
            assert len(h["judul_en"]) >= 3 and len(h["judul_id"]) >= 3
            assert len(set(h["judul_en"])) == len(h["judul_en"])
            low = (h["deskripsi_en"] + h["deskripsi_id"]).lower()
            assert all(w not in low for w in judul.KATA["terlarang"])


def test_title_matches_the_audio():
    r, _ = _r("deep_sleep", 1)
    h = judul.buat(r)
    assert h["tujuan"] == "tidur"
    assert any("Piano" in t for t in h["judul_en"])                 # melodi piano disebut
    r, _ = _r("meditation", 1)
    h = judul.buat(r)
    assert not any("Bells" in t or "Piano" in t or "Kalimba" in t for t in h["judul_en"])   # tanpa melodi


def test_youtube_chapters_valid():
    r, secs = _r("nebula", 2001)
    ch = judul.buat(r, sections=secs)["chapter"]
    assert len(ch) >= 3 and ch[0][0] == "0:00"
    to_s = lambda t: sum(int(x) * 60 ** i for i, x in enumerate(reversed(t.split(":"))))
    secs_list = [to_s(t) for t, _, _ in ch]
    assert all(b - a >= 10 for a, b in zip(secs_list, secs_list[1:]))
    assert len({n for _, n, _ in ch}) == len(ch)                   # nama tidak berulang


def test_deterministic_and_avoids_previous_titles():
    r, _ = _r("orbit", 7)
    a = judul.buat(r)
    assert a == judul.buat(r)
    b = judul.buat(r, hindari=a["judul_en"])
    assert not set(a["judul_en"]) & set(b["judul_en"])


def test_three_hour_chapters():
    r, secs = _r("deep_sleep", 1001, menit=180)
    h = judul.buat(r, sections=secs)
    ch = h["chapter"]
    assert ch[0][0] == "0:00" and ch[-1][0].count(":") == 2      # format jam untuk video panjang
    assert len({n for _, n, _ in ch}) == len(ch)                  # tetap tidak ada nama kembar
    assert any("3 Hours" in t for t in h["judul_en"])
