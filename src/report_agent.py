"""Agent nr. 2: ugerapport om de kampe, hvor modellen og markedet er mest uenige.

Arbejdsdeling:
  KODE   vælger de N kampe med størst uenighed (deterministisk, fra tabellen predictions)
  AGENT  søger nyheder (skader, karantæner, trænerskifte, form), kan slå data op med run_sql,
         og vurderer, om nyhederne forklarer uenigheden
  KODE   kontrollerer rapporten (save_report) – alle kampe nævnt, kilder med links –
         og gemmer den i reports/

Vigtigt: backtesten viste, at markedet næsten altid har ret, når det er uenigt med modellen.
Rapporten er en analyse af uenigheden, IKKE spilforslag.

Kør:  uv run python src/report_agent.py
"""
import os
import sqlite3
from datetime import datetime, timezone

import anthropic
import pandas as pd

from agent import DB, RUN_SQL_TOOL, run_agent, run_sql

N_MATCHES = 3
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]   # Sonnet bruges kun, hvis Haiku afviser web search
LANGUAGE = "English"                                 # skift til "Danish", hvis du vil have rapporten på dansk
REPORT_DIR = "reports"

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 6}   # 1 søgning pr. hold

# Binært fra 2026-10-27 (før: explained/partly/not_explained – 13 af 15 blev "partly", så det målte intet)
LEANS = ["market", "model"]

SAVE_REPORT_TOOL = {
    "name": "save_report",
    "description": (
        "Save the finished weekly report. `markdown`: the full report – it must cover every match you were "
        "given (use the exact team names), give a lean (market or model) per match, and end with a 'Sources' section listing "
        "the URLs you relied on. `verdicts`: the same verdicts in structured form, one per match, so they can "
        "be evaluated against the results later. The tool validates both and returns problems if incomplete."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "markdown": {"type": "string", "description": "The full report in Markdown."},
            "verdicts": {
                "type": "array",
                "description": "One entry per match, same order as given.",
                "items": {
                    "type": "object",
                    "properties": {
                        "home": {"type": "string", "description": "Exact home team name as given."},
                        "away": {"type": "string", "description": "Exact away team name as given."},
                        "lean": {"type": "string", "enum": LEANS,
                                 "description": "Which will give the actual result the higher probability: "
                                                "'market' or 'model'. No middle option."},
                        "reason": {"type": "string",
                                   "description": "One sentence citing ONE concrete, checkable fact behind the "
                                                  "lean: a result with date and score, a named injured or "
                                                  "suspended player, a line-up or coaching change."},
                        "p_home": {"type": "number", "description": "YOUR probability of a home win (0-1)."},
                        "p_draw": {"type": "number", "description": "YOUR probability of a draw (0-1)."},
                        "p_away": {"type": "number", "description": "YOUR probability of an away win (0-1)."},
                    },
                    "required": ["home", "away", "lean", "reason", "p_home", "p_draw", "p_away"],
                },
            },
        },
        "required": ["markdown", "verdicts"],
    },
}

SYSTEM = (
    "You are a football data analyst covering the Japanese J2 League. A simple Poisson model and the "
    "betting market (Pinnacle, margin removed) disagree on some upcoming matches. A backtest over 4,000+ "
    "matches showed the market is usually right when they disagree, because it prices in information the "
    "model does not see (injuries, suspensions, line-ups, coaching changes, form, motivation).\n\n"
    "For each match: search for recent news on BOTH teams (English and Japanese sources are both fine), "
    "use the 'Recent results' given for each team (already computed from the database, from that team's "
    "own perspective – copy home/away and scores exactly as given, never re-derive them), "
    "and judge which side is closer to the truth.\n"
    "Lean per match: 'market' or 'model' – which of the two you expect to give the actual result the "
    "higher probability. There is no middle option; you must pick one. Back it with one sentence citing "
    "ONE concrete, checkable fact (a result with date and score, a named injured or suspended player, a "
    "line-up or coaching change). State it in the report as e.g. 'Lean: market – <reason>'. "
    "Be concrete and cite sources. Never give betting advice.\n"
    "Write news in your own words (no verbatim quotes, no citation markup); list the links under 'Sources'.\n"
    "Finally, give YOUR OWN forecast per match (p_home, p_draw, p_away, summing to 1), using the model, the "
    "market and the news. Your forecasts are scored against the market by log loss, so only move away from "
    "the market for a concrete reason. News from before a team's most recent match is already partly "
    "reflected in its results (and in the model); news since the last match is new information. "
    "State your forecast in the report as e.g. 'Agent forecast: 45/27/28'.\n"
    f"Write the report in {LANGUAGE}, under 600 words, then call save_report with both the markdown "
    "and the structured verdicts (lean: market / model)."
)


def top_disagreements(n=N_MATCHES):
    """De n kommende kampe med størst afstand mellem model og Pinnacle (seneste forudsigelse)."""
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        """
        SELECT * FROM predictions
        WHERE predicted_at = (SELECT MAX(predicted_at) FROM predictions)
          AND start_time > ?
          AND pin_p1 IS NOT NULL
        """,
        con,
        params=(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),),
    )
    con.close()
    if df.empty:
        return df
    df["disagree"] = df[["p1", "pX", "p2"]].sub(df[["pin_p1", "pin_pX", "pin_p2"]].values).abs().max(axis=1)
    return df.sort_values("disagree", ascending=False).head(n)


def recent_form(team, n=5):
    """Holdets seneste n resultater, set fra HOLDETS side (W/D/L, hjemme/ude), med modellens holdnavne.

    Koden afgør hjemme/ude og resultat – ikke LLM'en. Første rapport havde to hjemme/ude-fejl,
    fordi agenten selv skulle læse home/away-kolonnerne (og op_results bruger OddsPapi-navne).
    """
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        """
        SELECT r.start_time,
               COALESCE(mh.canonical, r.home) AS home,
               COALESCE(ma.canonical, r.away) AS away,
               r.home_goals, r.away_goals
        FROM op_results r
        LEFT JOIN team_map mh ON mh.source = 'oddspapi' AND mh.name = r.home
        LEFT JOIN team_map ma ON ma.source = 'oddspapi' AND ma.name = r.away
        """,
        con,
    )
    # Runde 1-10 ligger i Excel-tabellen (dato som MM/DD/YYYY, allerede med modellens navne)
    manual = pd.read_sql("SELECT date, home, away, home_goals, away_goals FROM manual_matches", con)
    con.close()
    manual["start_time"] = pd.to_datetime(manual["date"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
    df = pd.concat([df, manual.drop(columns="date")], ignore_index=True)
    df["day"] = df["start_time"].str[:10]
    df = df.drop_duplicates(subset=["day", "home", "away"])
    df = df[(df.home == team) | (df.away == team)].sort_values("start_time", ascending=False).head(n)
    lines = []
    for r in df.itertuples():
        at_home = r.home == team
        gf, ga = (r.home_goals, r.away_goals) if at_home else (r.away_goals, r.home_goals)
        res = "W" if gf > ga else "D" if gf == ga else "L"
        venue = f"at home vs {r.away}" if at_home else f"away at {r.home}"
        lines.append(f"    {r.start_time[:10]}: {res} {gf}-{ga} {venue}")
    return "\n".join(lines) or "    (no results in database)"


def describe(df):
    lines = []
    for r in df.itertuples():
        lines.append(
            f"- {r.home} vs {r.away} (kick-off {r.start_time[:16]} UTC): "
            f"model home/draw/away {r.p1:.0%}/{r.pX:.0%}/{r.p2:.0%}, "
            f"Pinnacle {r.pin_p1:.0%}/{r.pin_pX:.0%}/{r.pin_p2:.0%} "
            f"(largest gap {r.disagree * 100:.0f} percentage points)\n"
            f"  Recent results {r.home} (own perspective, score = {r.home}'s goals first):\n{recent_form(r.home)}\n"
            f"  Recent results {r.away} (own perspective, score = {r.away}'s goals first):\n{recent_form(r.away)}"
        )
    return "\n".join(lines)


def save_verdicts(rows):
    """Gem vurderingerne struktureret, så eval_reports.py kan måle dem mod resultaterne."""
    con = sqlite3.connect(DB)
    con.execute("""
        CREATE TABLE IF NOT EXISTS report_verdicts (
            created_at    TEXT,
            report_path   TEXT,
            predicted_at  TEXT,   -- hvilken forudsigelse vurderingen bygger på (join til predictions)
            fixture_id    TEXT,
            home          TEXT,
            away          TEXT,
            verdict       TEXT,   -- explained / partly / not_explained (kun til og med 2026-10-26)
            reason        TEXT
        )""")
    have = {r[1] for r in con.execute("PRAGMA table_info(report_verdicts)")}
    for col, typ in [("agent_p1", "REAL"), ("agent_pX", "REAL"), ("agent_p2", "REAL"),  # fra 2026-10-22
                     ("lean", "TEXT")]:                                               # fra 2026-10-27
        if col not in have:
            con.execute(f"ALTER TABLE report_verdicts ADD COLUMN {col} {typ}")
    con.executemany(
        "INSERT INTO report_verdicts (created_at, report_path, predicted_at, fixture_id, home, away, "
        "verdict, lean, reason, agent_p1, agent_pX, agent_p2) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def normalise(v):
    ps = [v["p_home"], v["p_draw"], v["p_away"]]
    return [x / sum(ps) for x in ps]


def round_table(given):
    """Alle kommende kampe i runden: model vs. marked (+ agentens bud, hvor den har givet et). Laves af koden."""
    df = top_disagreements(n=100).sort_values("start_time")
    out = ["## All matches this round (computed by code, H/D/A %)", "",
           "| Kickoff (UTC) | Match | Model | Market | Agent | Largest gap |", "|---|---|---|---|---|---|"]
    f = lambda a, b, c: f"{a:.0%}/{b:.0%}/{c:.0%}".replace("%", "")
    for r in df.itertuples():
        g = given.get((r.home, r.away))
        agent = f(*normalise(g)) if g else "–"
        out.append(f"| {r.start_time[5:16].replace('T', ' ')} | {r.home} – {r.away} | {f(r.p1, r.pX, r.p2)} | "
                   f"{f(r.pin_p1, r.pin_pX, r.pin_p2)} | {agent} | {r.disagree * 100:.0f} pts |")
    return "\n".join(out) + "\n"


def make_save_report(matches):
    """Byg save_report-funktionen, så den kender de kampe, rapporten SKAL dække."""
    def save_report(markdown, verdicts=None):
        problems = []
        for r in matches.itertuples():
            for team in (r.home, r.away):
                if team not in markdown:
                    problems.append(f"Team not mentioned with exact name: {team}")
        if "http" not in markdown:
            problems.append("No source URLs found – add a 'Sources' section with links.")
        # Rå citat-markup fra web_search slap igennem i rapporten 2026-10-22 (ordrette citater + kodeaffald)
        if "cite index" in markdown or "</cite>" in markdown:
            problems.append("Remove all citation markup (cite index=...>...</cite>). Write the news in your own "
                            "words and put the links in the 'Sources' section – no verbatim quotes.")
        if len(markdown) > 8000:
            problems.append(f"Report too long ({len(markdown)} characters, max 8000).")

        # De strukturerede vurderinger: præcis én pr. kamp, med gyldig værdi
        verdicts = verdicts or []
        expected = {(r.home, r.away): r for r in matches.itertuples()}
        given = {(v.get("home"), v.get("away")): v for v in verdicts}
        missing = [f"{h} vs {a}" for (h, a) in expected if (h, a) not in given]
        unknown = [f"{h} vs {a}" for (h, a) in given if (h, a) not in expected]
        bad = [v.get("lean") for v in verdicts if v.get("lean") not in LEANS]
        for v in verdicts:
            ps = [v.get("p_home"), v.get("p_draw"), v.get("p_away")]
            if any(not isinstance(x, (int, float)) for x in ps):
                problems.append(f"{v.get('home')} vs {v.get('away')}: p_home/p_draw/p_away must all be numbers.")
            elif not all(0.01 <= x <= 0.98 for x in ps) or abs(sum(ps) - 1) > 0.03:
                problems.append(f"{v.get('home')} vs {v.get('away')}: probabilities {ps} must each be "
                                "0.01-0.98 and sum to 1.")
        if missing:
            problems.append(f"Missing structured verdicts for: {missing}")
        if unknown:
            problems.append(f"Verdicts for matches not in this report (check exact names): {unknown}")
        if bad:
            problems.append(f"Invalid lean values {bad} – use one of {LEANS}")
        if problems:
            return "NOT SAVED. Problems:\n- " + "\n- ".join(problems), True

        markdown = markdown.rstrip() + "\n\n" + round_table(given)
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = f"{REPORT_DIR}/report_{datetime.now().strftime('%Y-%m-%d')}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(markdown)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        save_verdicts([
            (now, path, r.predicted_at, r.fixture_id, r.home, r.away,
             None, given[(r.home, r.away)]["lean"], given[(r.home, r.away)].get("reason", ""),
             *normalise(given[(r.home, r.away)]))
            for r in matches.itertuples()
        ])
        return f"SAVED to {path} (+ {len(matches)} verdicts in report_verdicts)", False
    return save_report


def main(client=None):
    matches = top_disagreements()
    if matches.empty:
        print("Ingen kommende kampe i predictions. Kør fetch_weekly.py og predict_upcoming.py først.")
        return None

    task = ("Write this week's J2 report. The matches with the largest model-vs-market disagreement:\n"
            + describe(matches))
    tools = [RUN_SQL_TOOL, WEB_SEARCH_TOOL, SAVE_REPORT_TOOL]
    funcs = {"run_sql": run_sql, "save_report": make_save_report(matches)}

    for model in MODELS:
        try:
            final, record = run_agent(task, SYSTEM, tools, funcs, client=client, model=model,
                                      max_turns=15, max_total_tokens=150_000, max_tokens_per_call=8192,
                                      required_tool="save_report")
            break
        except anthropic.BadRequestError as e:
            if "web_search" in str(e) and model != MODELS[-1]:
                print(f"{model} afviste web search – prøver {MODELS[MODELS.index(model) + 1]}")
                continue
            raise

    print("\nAgentens afslutning:\n" + final)
    if not record["required_done"]:
        print("\nADVARSEL: rapporten blev IKKE gemt. Se stop_reasons i data/agent_log.jsonl:",
              record["stop_reasons"])
    return record


if __name__ == "__main__":
    main()
