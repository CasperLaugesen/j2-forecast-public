"""Agent-kernen: en LLM, der selv vælger værktøjer i en løkke, indtil opgaven er løst.

Princippet (uden frameworks):
  1. Send opgave + liste af værktøjer til modellen.
  2. Hvis modellen svarer med stop_reason == "tool_use", kører VORES kode værktøjet
     og sender resultatet tilbage som "tool_result".
  3. Gentag, indtil modellen svarer med tekst (stop_reason == "end_turn")
     – eller indtil et sikkerhedsloft rammes.

To slags værktøjer:
  - Klient-værktøjer (run_sql, save_...): VORES python-kode kører dem.
  - Server-værktøjer (web_search): Anthropic kører dem. Resultaterne kommer direkte i
    svaret, og vi skal bare sende svaret uændret tilbage i næste runde.
    Ved lange søgninger kan API'et svare stop_reason == "pause_turn" -> vi fortsætter blot.

Sikkerhedslofter (så en løkke aldrig kan løbe løbsk):
  max_turns        – maks. antal runder frem og tilbage
  max_total_tokens – maks. samlet antal tokens pr. kørsel
"""
import json
import sqlite3
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-5-5"
# dollar pr. million tokens (input, output)
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0)}
# Haiku 5.5 koster 5x mere, når ét kald har over 100.000 input-tokens (fx mange søgeresultater)
PRICES_LONG_PROMPT = {"claude-haiku-5-5": (0.50, 2.50)}
LONG_PROMPT = 100_000
WEB_SEARCH_PRICE = 0.01                   # dollar pr. søgning


def call_cost(model, tokens_in, tokens_out):
    """Prisen for ÉT API-kald. Prisen afhænger af kaldets egen prompt-længde."""
    price_in, price_out = PRICES.get(model, (0, 0))
    if tokens_in > LONG_PROMPT and model in PRICES_LONG_PROMPT:
        price_in, price_out = PRICES_LONG_PROMPT[model]
    return tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
MAX_TURNS = 12
MAX_TOKENS = 50_000
DB = "data/j2.db"
LOG = "data/agent_log.jsonl"


# ---------------------------------------------------------------------------
# Værktøj: run_sql  (kun læseadgang)
# ---------------------------------------------------------------------------
RUN_SQL_TOOL = {
    "name": "run_sql",
    "description": (
        "Run a read-only SQL query (SQLite) against the project database and get the rows back as JSON. "
        "Only SELECT/WITH queries are allowed. Use `SELECT name, sql FROM sqlite_master WHERE type='table'` "
        "to discover tables and columns. Results are capped at 200 rows."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "A single SQLite SELECT query."}},
        "required": ["query"],
    },
}


def run_sql(query):
    q = query.strip().lower()
    if not (q.startswith("select") or q.startswith("with")):
        return "ERROR: only SELECT/WITH queries are allowed.", True
    # mode=ro: databasen åbnes skrivebeskyttet – selv en "snedig" forespørgsel kan ikke ændre data
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.execute(query)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(200)]
        return json.dumps(rows, ensure_ascii=False), False
    except sqlite3.Error as e:
        return f"ERROR: {e}", True                 # fejlen sendes tilbage, så modellen kan rette sin SQL
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Selve agent-løkken – genbruges af alle agenter i projektet
# ---------------------------------------------------------------------------
def run_agent(task, system, tools, tool_functions, client=None, verbose=True,
              model=MODEL, max_turns=MAX_TURNS, max_total_tokens=MAX_TOKENS, max_tokens_per_call=2048,
              required_tool=None, max_nudges=2):
    """Kør agent-løkken. tool_functions: {"tool_name": python_funktion}.
    Hver python_funktion returnerer (tekst, is_error).
    required_tool: hvis sat, er opgaven først løst, når dette værktøj er kørt uden fejl.
    Stopper modellen før, får den en påmindelse (højst max_nudges gange)."""
    client = client or anthropic.Anthropic()
    messages = [{"role": "user", "content": task}]
    tokens_in = tokens_out = searches = nudges = 0
    cost = 0.0
    steps, stop_reasons = [], []
    required_done = required_tool is None
    final, error, turn = "", None, 0

    for turn in range(1, max_turns + 1):
        try:
            resp = client.messages.create(
                model=model, max_tokens=max_tokens_per_call, system=system, tools=tools, messages=messages,
            )
        except anthropic.APIError as e:             # log kørslen (og hvad den nåede at koste), og rejs fejlen igen
            error, final = e, f"FEJL fra API: {e}"
            break
        tokens_in += resp.usage.input_tokens
        tokens_out += resp.usage.output_tokens
        cost += call_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        stu = getattr(resp.usage, "server_tool_use", None)
        searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        stop_reasons.append(resp.stop_reason)

        # Server-værktøjer (web_search) er allerede kørt af Anthropic – vis hvad der blev søgt på
        for block in resp.content:
            if block.type == "server_tool_use":
                steps.append({"turn": turn, "tool": block.name, "input": block.input, "is_error": False})
                if verbose:
                    print(f"[{turn}] {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}) -> server")

        if resp.stop_reason == "pause_turn":            # lang server-søgning: send svaret tilbage og fortsæt
            messages.append({"role": "assistant", "content": resp.content})
            continue

        if resp.stop_reason == "max_tokens":            # svaret blev afskåret: bed om at fortsætte kortere
            messages.append({"role": "assistant", "content": resp.content})
            note = ("Your last response was cut off because it was too long. Continue from where "
                    "you stopped, keep it short, and use your tools to finish the task.")
            # Et afskåret værktøjskald har et ufuldstændigt input. API'et kræver alligevel et
            # tool_result til hvert tool_use – så vi svarer med en fejl i stedet for at køre det.
            cut = [b for b in resp.content if b.type == "tool_use"]
            content = [{"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                        "content": "This tool call was cut off before it was complete and was NOT run. "
                                   "Call it again with shorter input."} for b in cut]
            content.append({"type": "text", "text": note})
            messages.append({"role": "user", "content": content})
            if verbose:
                print(f"[{turn}] svar afskåret (max_tokens) – beder agenten fortsætte"
                      + (f" ({len(cut)} afskåret værktøjskald afvist)" if cut else ""))
            continue

        if resp.stop_reason != "tool_use":
            final = "".join(b.text for b in resp.content if b.type == "text")
            if not required_done and nudges < max_nudges:  # stoppede for tidligt: påmind om opgaven
                nudges += 1
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content":
                                 f"You have not completed the task: call {required_tool} successfully."})
                if verbose:
                    print(f"[{turn}] agenten stoppede uden {required_tool} – påmindelse {nudges}/{max_nudges}")
                continue
            break

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":              # kun klient-værktøjer køres af os
                continue
            func = tool_functions.get(block.name)
            if func is None:
                output, is_error = f"ERROR: unknown tool {block.name}", True
            else:
                output, is_error = func(**block.input)
            if block.name == required_tool and not is_error:
                required_done = True
            steps.append({"turn": turn, "tool": block.name, "input": block.input,
                          "is_error": is_error, "output": output[:500]})
            if verbose:
                status = "FEJL" if is_error else "ok"
                print(f"[{turn}] {block.name}({json.dumps(block.input, ensure_ascii=False)[:120]}) -> {status}")
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})

        if tokens_in + tokens_out > max_total_tokens:
            final = f"STOPPET: tokenloft på {max_total_tokens} nået"
            break
    else:
        final = f"STOPPET: maks. {max_turns} runder nået"

    cost += searches * WEB_SEARCH_PRICE
    record = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model, "task": task[:200], "turns": turn, "stop_reasons": stop_reasons,
        "required_tool": required_tool, "required_done": required_done, "steps": steps,
        "tokens_in": tokens_in, "tokens_out": tokens_out, "web_searches": searches,
        "cost_usd": round(cost, 6), "final": final,
    }
    with open(LOG, "a", encoding="utf-8") as f:              # én linje pr. kørsel – sporbarhed
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if verbose:
        print(f"\n{model}: {turn} runder, {tokens_in} tokens ind, {tokens_out} ud, "
              f"{searches} søgninger – ca. ${cost:.4f}")
    if error is not None:
        raise error
    return final, record
