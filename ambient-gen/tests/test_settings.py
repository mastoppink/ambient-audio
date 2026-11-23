import sys, pathlib, tomllib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pytest
import config
import settings
from compose import compose


def test_presets_load_and_apply():
    for p in (ROOT / "presets").glob("*.toml"):
        r = settings.resolve(settings.load(p), 1)
        settings.apply(r)
        scale = {(config.TONIC_MIDI + s) % 12 for s in config.SCALE}
        assert all(e.midi % 12 in scale for e in compose(200, 1, with_melody=True))


def test_ranges_are_deterministic_and_within_bounds():
    s = settings.load(overrides=["pad.brightness=[0.2, 0.4]"])
    a = settings.resolve(s, 5)["pad"]["brightness"]
    assert a == settings.resolve(s, 5)["pad"]["brightness"]
    assert 0.2 <= a <= 0.4
    assert settings.resolve(s, 5)["pad"]["chord_seconds"] == [50, 80]  # rentang asli tidak diacak


def test_overrides_text_and_numbers():
    s = settings.load(overrides=["key.mode=dorian", "melody.density=0.1", "key.tonic=F#"])
    assert s["key"]["mode"] == "dorian" and s["melody"]["density"] == 0.1 and s["key"]["tonic"] == "F#"


def test_resolved_toml_roundtrip(tmp_path):
    r = settings.resolve(settings.load(ROOT / "presets/nebula.toml"), 77)
    f = tmp_path / "x.toml"
    f.write_text(settings.to_toml(r))
    assert settings.resolve(settings.load(f), 77) == r


def test_preview_is_start_of_long_version():
    settings.apply(settings.resolve(settings.load(), 9))
    short = [e for e in compose(150, 9, with_melody=True) if e.layer != "drone"]
    long_ = [e for e in compose(1200, 9, with_melody=True) if e.layer != "drone"]
    first = [(e.start, e.midi, e.layer) for e in long_ if e.start < 100]
    assert first == [(e.start, e.midi, e.layer) for e in short if e.start < 100]


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        settings.apply(settings.resolve(settings.load(overrides=["key.mode=locrian"]), 1))
