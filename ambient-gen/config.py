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
