"""Tests af evalueringen af rapport-agenten. Kør:  uv run pytest"""
import sqlite3

import pandas as pd

import eval_reports
import report_agent


def test_first_lean_is_locked():
    # Samme kamp vurderet tre gange: kun den første lean tæller, uanset hvad genkørslerne siger.
    df = pd.DataFrame({
        "fixture_id": ["A", "A", "A"],
        "created_at": ["2026-10-28T07:00:00", "2026-10-28T07:30:00", "2026-10-28T08:00:00"],
        "lean": ["market", "model", "model"],
    })
    df = df.sample(frac=1, random_state=1)           # rækkefølgen i tabellen må ikke betyde noget

    first = eval_reports.first_per_fixture(df, "lean")

    assert first.lean.tolist() == ["market"]


def test_field_scored_from_first_row_that_has_it():
    # Agentens prognose kom først med i genkørslen (som 22/10): så er DEN første prognose den låste.
    df = pd.DataFrame({
        "fixture_id": ["A", "A", "A"],
        "created_at": ["2026-10-22T07:06:13", "2026-10-22T07:32:27", "2026-10-22T08:00:00"],
        "p_agent": [None, 0.55, 0.30],
    })

    first = eval_reports.first_per_fixture(df, "p_agent")

    assert first.p_agent.tolist() == [0.55]


def test_rerun_does_not_change_scored_lean(tmp_path, monkeypatch):
    # Hele vejen: save_verdicts gemmer to kørsler af samme kamp, eval_reports scorer kun den første.
    db = str(tmp_path / "test.db")
    out = str(tmp_path / "evaluation.md")
    monkeypatch.setattr(report_agent, "DB", db)
    monkeypatch.setattr(eval_reports, "DB", db)
    monkeypatch.setattr(eval_reports, "OUT", out)

    con = sqlite3.connect(db)
    con.execute("CREATE TABLE predictions (fixture_id, predicted_at, p1, pX, p2, pin_p1, pin_pX, pin_p2)")
    con.execute("INSERT INTO predictions VALUES ('F1', 'T0', 0.30, 0.30, 0.40, 0.50, 0.27, 0.23)")
    con.execute("CREATE TABLE op_results (fixture_id, home_goals, away_goals)")
    con.execute("INSERT INTO op_results VALUES ('F1', 2, 0)")      # hjemmesejr: markedet var tættest
    con.commit()
    con.close()

    run = lambda created, lean: (created, "r.md", "T0", "F1", "Home FC", "Away FC",
                                 None, lean, "reason", 0.4, 0.3, 0.3)
    report_agent.save_verdicts([run("2026-10-28T07:00:00", "market")])
    report_agent.save_verdicts([run("2026-10-28T07:30:00", "model")])   # genkørsel med modsat lean

    eval_reports.main()
    text = open(out, encoding="utf-8").read()

    assert "| Agent's lean (1 market, 0 model) | 1 | 100% |" in text
    assert "| Home FC – Away FC | – | market |" in text


def test_all_settled_uses_latest_prediction_before_kickoff(tmp_path, monkeypatch):
    # Tre forudsigelser af samme kamp: kun den seneste FØR kickoff tæller, aldrig én efter kickoff.
    db = str(tmp_path / "test.db")
    monkeypatch.setattr(eval_reports, "DB", db)

    con = sqlite3.connect(db)
    con.execute("CREATE TABLE predictions (fixture_id, predicted_at, start_time, home, away, "
                "p1, pX, p2, pin_p1, pin_pX, pin_p2)")
    kickoff = "2026-10-25T05:00:00.000Z"
    con.executemany("INSERT INTO predictions VALUES (?, ?, ?, 'Home FC', 'Away FC', ?, ?, ?, ?, ?, ?)", [
        ("F1", "2026-10-21T10:00:00", kickoff, 0.20, 0.30, 0.50, 0.30, 0.30, 0.40),   # tidlig
        ("F1", "2026-10-24T10:00:00", kickoff, 0.40, 0.30, 0.30, 0.52, 0.26, 0.26),   # senere, før kickoff
        ("F1", "2026-10-25T06:00:00", kickoff, 0.90, 0.05, 0.05, 0.90, 0.05, 0.05),   # efter kickoff
        ("F2", "2026-10-24T10:00:00", kickoff, 0.40, 0.30, 0.30, 0.50, 0.25, 0.25),   # intet resultat
    ])
    con.execute("CREATE TABLE op_results (fixture_id, start_time, home_goals, away_goals)")
    con.execute("INSERT INTO op_results VALUES ('F1', ?, 2, 0)", (kickoff,))      # hjemmesejr
    con.execute("INSERT INTO op_results VALUES ('F2', ?, NULL, NULL)", (kickoff,))
    con.commit()

    df = eval_reports.load_all_settled(con)
    con.close()

    assert df.fixture_id.tolist() == ["F1"]
    assert df.p_model.iloc[0] == 0.40
    assert abs(df.p_market.iloc[0] - 0.52 / 1.04) < 1e-9          # margin fjernet
