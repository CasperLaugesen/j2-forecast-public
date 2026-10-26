"""Evaluer navne-agenten mod et facit, som et menneske har lavet.

Facit: de 6 hold, hvor OddsPapi og din Excel bruger forskellige navne.
De øvrige 14 hold hedder det samme i begge kilder og skal kobles til sig selv.
TJEK SELV FACIT – det er dit ansvar, at det er rigtigt.
"""
import sqlite3

DB = "data/j2.db"

DIFFERENT_NAMES = {
    "Hokkaido Consadole Sapporo": "Consadole Sapporo",
    "RB Omiya Ardija": "Omiya Ardija",
    "Iwaki FC": "Iwaki SC",
    "Vanraure Hachinohe FC": "Vanraure Hachinohe",
    "Tegevajaro Miyazaki": "Tegevajaro Miyazaki FC",
    "Blaublitz Akita": "AFC Blaublitz Akita",
}


def main():
    con = sqlite3.connect(DB)
    source = {r[0] for r in con.execute("SELECT home FROM op_fixtures UNION SELECT away FROM op_fixtures")}
    truth = {name: DIFFERENT_NAMES.get(name, name) for name in source}
    try:
        saved = dict(con.execute("SELECT name, canonical FROM team_map WHERE source = 'oddspapi'").fetchall())
    except sqlite3.OperationalError:
        saved = {}
    con.close()

    correct = [n for n in truth if saved.get(n) == truth[n]]
    wrong = [n for n in truth if n in saved and saved[n] != truth[n]]
    missing = [n for n in truth if n not in saved]

    print(f"Korrekte: {len(correct)}/{len(truth)}")
    print(f"  heraf svære (forskellige navne): "
          f"{sum(1 for n in correct if n in DIFFERENT_NAMES)}/{len(DIFFERENT_NAMES)}")
    for n in wrong:
        print(f"FORKERT: {n} -> {saved[n]} (facit: {truth[n]})")
    for n in missing:
        print(f"MANGLER: {n}")


if __name__ == "__main__":
    main()
