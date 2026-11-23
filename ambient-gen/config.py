"""Parameter global Spacenight."""
SAMPLE_RATE = 48_000
SEED = 20261123

# D Lydian: D E F# G# A B C#  (semiton dari tonika)
TONIC_MIDI = 50  # D3
SCALE = [0, 2, 4, 6, 7, 9, 11]

PAD = dict(
    n_osc=5,            # jumlah oscillator per kanal
    detune_cents=9.0,   # sebaran detune maksimum (±)
    harmonics=12,       # saw band-limited (aditif)
    saw_mix=0.55,       # sisanya triangle
    sub_level=0.35,     # sinus satu oktaf di bawah
    attack=10.0,
    release=14.0,
    cutoff_min=500.0,   # Hz
    cutoff_max=2200.0,
    lfo_period=45.0,    # detik
)

DRONE = dict(
    PAD,
    n_osc=3,
    detune_cents=4.0,
    saw_mix=0.25,       # lebih lembut
    sub_level=0.0,      # drone sudah rendah; hindari penumpukan < 80 Hz
    attack=15.0,
    release=20.0,
    cutoff_min=180.0,
    cutoff_max=650.0,
    lfo_period=83.0,
)
DRONE_NOTES = [38, 45]  # D2 + A2
DRONE_LEVEL = 0.8

PAD_LEVEL = 0.55
PAD_RANGE = (52, 74)        # E3..D5: rentang nada chord
CHORD_SECONDS = (50, 80)    # durasi tiap chord (plan final: 60-120)
CHORD_OVERLAP = 12.0        # detik tumpang-tindih antar chord (crossfade)

# --- Milestone 3 ---
MELODY = dict(
    gap=(15.0, 40.0),     # jeda antar nada (detik)
    range=(62, 86),       # D4..D6
    attack=1.2,
    decay=9.0,            # waktu turun eksponensial
    level=0.22,
    rest_prob=0.25,       # peluang jeda ekstra
)
TEXTURE = dict(
    level=0.05,
    band_lo=300.0, band_hi=3500.0,   # pusat band-pass digerakkan LFO
    lfo_periods=(17.0, 23.0, 29.0),  # loop prima -> pola tidak terasa berulang
)
FX = dict(
    reverb_decay=11.0,    # detik (RT60 IR sintetis)
    reverb_predelay=0.03,
    reverb_hp=180.0,      # high-pass di jalur reverb: cegah keruh
    send=dict(drone=0.25, pad=0.45, melody=0.85, texture=0.6),
    delay_seconds=0.75 * 60 / 50,   # titik-titik delay panjang
    delay_feedback=0.3,
    delay_mix=0.25,       # hanya untuk melodi
    target_lufs=-16.0,
    ceiling_db=-1.0,
)

# --- Milestone 3.5 ---
CHORD_WEIGHTS = {}          # override bobot chord dari preset, mis. {"II": 4.0}
MIX = dict(dry=0.75, wet=1.0)

# --- Milestone 4 ---
SHAPE = None              # fungsi kurva intensitas t -> 0..1 (form.py), None = datar
SEGMENT_SECONDS = 30.0    # unit render paralel
