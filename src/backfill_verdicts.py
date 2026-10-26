"""ENGANGSSCRIPT: gem vurderingerne fra de to første rapporter (19/10) i report_verdicts.

De blev skrevet, før save_report gemte vurderinger struktureret. Vurderingerne er
aflæst manuelt fra rapporterne. To kørsler af samme kampe -> giver også et første
konsistens-datapunkt (Montedio – Sapporo fik to forskellige vurderinger).

Kør ÉN gang:  uv run python src/backfill_verdicts.py
"""
import sqlite3

from report_agent import save_verdicts

DB = "data/j2.db"

RUNS = [
    # (tidspunkt for rapporten, forudsigelsen den byggede på, {kamp: vurdering})
    ("2026-10-19T10:20:00", "2026-10-19T10:10:47", {
        ("Albirex Niigata", "Sagan Tosu"): "partly",
        ("Jubilo Iwata", "Oita Trinita"): "partly",
        ("Montedio Yamagata", "Consadole Sapporo"): "not_explained",
    }),
    ("2026-10-19T10:36:00", "2026-10-19T10:35:41", {
        ("Albirex Niigata", "Sagan Tosu"): "partly",
        ("Jubilo Iwata", "Oita Trinita"): "partly",
        ("Montedio Yamagata", "Consadole Sapporo"): "partly",
    }),
]


def main():
    con = sqlite3.connect(DB)
    try:
        done = con.execute("SELECT COUNT(*) FROM report_verdicts WHERE created_at < '2026-10-20'").fetchone()[0]
    except sqlite3.OperationalError:
        done = 0
    if done:
        print("Allerede kørt – intet gjort.")
        return
    rows = []
    for created, predicted_at, verdicts in RUNS:
        for (home, away), verdict in verdicts.items():
            fid = con.execute(
                "SELECT fixture_id FROM predictions WHERE predicted_at = ? AND home = ? AND away = ?",
                (predicted_at, home, away)).fetchone()
            if fid is None:
                print(f"Fandt ikke {home} – {away} i predictions {predicted_at} – springer over")
                continue
            rows.append((created, "reports/report_2026-10-19.md", predicted_at, fid[0],
                         home, away, verdict, "backfilled from report text"))
    con.close()
    save_verdicts(rows)
    print(f"{len(rows)} vurderinger gemt.")


if __name__ == "__main__":
    main()
