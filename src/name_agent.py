"""Agent nr. 1: kobl holdnavne fra OddsPapi til navnene i din Excel-model.

Problem: OddsPapi skriver "Hokkaido Consadole Sapporo", din Excel skriver "Consadole Sapporo".
Uden en kobling kan modellen ikke forudsige OddsPapi-kampene.

Hvorfor en AGENT og ikke bare ét LLM-kald?
  - Agenten skal selv finde ud af, hvor navnene ligger (run_sql på databasen).
  - Når den gemmer en kobling, KONTROLLERER vores kode den (save_team_mapping).
    Er den forkert (manglende hold, ukendte navne, to hold koblet til samme navn),
    får agenten fejlen tilbage og skal rette den. LLM'en foreslår – koden kontrollerer.

Kør:  uv run python src/name_agent.py
Evaluér bagefter:  uv run python src/eval_name_agent.py
"""
import json
import sqlite3

from agent import DB, RUN_SQL_TOOL, run_agent, run_sql

SOURCE = "oddspapi"

SAVE_TOOL = {
    "name": "save_team_mapping",
    "description": (
        "Save the mapping from OddsPapi team names (tables op_fixtures.home/away) to the canonical team "
        "names used by the model (tables manual_matches.home/away). Every OddsPapi team must be mapped to "
        "exactly one canonical team, and no two OddsPapi teams may map to the same canonical team. "
        "The tool validates the mapping and returns a list of problems if it is not valid."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "mapping": {
                "type": "object",
                "description": 'Object {"<OddsPapi name>": "<canonical name>", ...}',
                "additionalProperties": {"type": "string"},
            }
        },
        "required": ["mapping"],
    },
}

SYSTEM = (
    "You are a careful data engineer. You match football team names between two data sources "
    "for the Japanese J2 League. Teams can appear with or without prefixes/suffixes such as "
    "'FC', 'SC', 'AFC', 'RB' or a city/region name ('Hokkaido'). Only map teams you are confident are the "
    "same club. Use the run_sql tool to look at the data – do not guess team names. "
    "When save_team_mapping returns problems, fix them and try again. "
    "Finish with a short summary of which names differed."
)

TASK = (
    "Map every team name in op_fixtures (OddsPapi) to the matching team name in manual_matches "
    "(the model's canonical names), then save it with save_team_mapping."
)


def teams(con, table):
    return {r[0] for r in con.execute(f"SELECT home FROM {table} UNION SELECT away FROM {table}")}


def save_team_mapping(mapping):
    con = sqlite3.connect(DB)
    source_teams = teams(con, "op_fixtures")
    canonical = teams(con, "manual_matches")

    problems = []
    missing = source_teams - set(mapping)
    if missing:
        problems.append(f"Missing OddsPapi teams: {sorted(missing)}")
    unknown_src = set(mapping) - source_teams
    if unknown_src:
        problems.append(f"These keys are not OddsPapi team names: {sorted(unknown_src)}")
    unknown_tgt = set(mapping.values()) - canonical
    if unknown_tgt:
        problems.append(f"These values are not canonical team names: {sorted(unknown_tgt)}")
    targets = list(mapping.values())
    dupes = {t for t in targets if targets.count(t) > 1}
    if dupes:
        problems.append(f"Several OddsPapi teams map to the same canonical team: {sorted(dupes)}")

    if problems:
        con.close()
        return "NOT SAVED. Problems:\n- " + "\n- ".join(problems), True

    con.execute("CREATE TABLE IF NOT EXISTS team_map (source TEXT, name TEXT, canonical TEXT, "
                "PRIMARY KEY (source, name))")
    con.execute("DELETE FROM team_map WHERE source = ?", (SOURCE,))
    con.executemany("INSERT INTO team_map VALUES (?,?,?)",
                    [(SOURCE, k, v) for k, v in mapping.items()])
    con.commit()
    con.close()
    changed = {k: v for k, v in mapping.items() if k != v}
    return f"SAVED {len(mapping)} teams. Names that differ: {json.dumps(changed, ensure_ascii=False)}", False


def main(client=None):
    final, record = run_agent(
        task=TASK,
        system=SYSTEM,
        tools=[RUN_SQL_TOOL, SAVE_TOOL],
        tool_functions={"run_sql": run_sql, "save_team_mapping": save_team_mapping},
        client=client,
        required_tool="save_team_mapping",
    )
    print("\nAgentens svar:\n" + final)
    return record


if __name__ == "__main__":
    main()
