"""Ukur 'bentrokan' melodi vs chord pad dari file .events.json.

Bentrokan = nada melodi yang TIDAK ada di chord dan berjarak 1 semiton (atau 11) dari
nada pad yang sedang bunyi. Ini interval yang paling terdengar sumbang dalam musik lambat.
Dicek di awal nada dan selama nada masih terdengar (sampai ~1.2 x decay).
"""
import json
import sys


def check(path, ring=10.0):
    ev = json.load(open(path))
    pads = [e for e in ev if e["layer"] == "pad"]
    mel = [e for e in ev if e["layer"] == "melody"]
    bad_start = bad_ring = 0
    for m in mel:
        def clash_at(t):
            act = {p["midi"] % 12 for p in pads if p["start"] <= t < p["start"] + p["dur"] - 6}
            if m["midi"] % 12 in act:      # nada yang sudah ada di chord tidak menambah kesumbangan
                return False
            return any((m["midi"] - a) % 12 in (1, 11) for a in act)
        if clash_at(m["start"] + 0.01):
            bad_start += 1
        elif any(clash_at(m["start"] + dt) for dt in (2, 4, 6, 8) if dt < ring):
            bad_ring += 1
    n = len(mel)
    return n, bad_start, bad_ring


if __name__ == "__main__":
    for p in sys.argv[1:]:
        n, a, b = check(p)
        print(f"{p}: {n} nada melodi | bentrok saat mulai: {a} ({a / max(n, 1):.0%}) | "
              f"bentrok saat chord berganti: {b} ({b / max(n, 1):.0%})")
