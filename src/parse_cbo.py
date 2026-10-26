"""Parse J2-odds fra CheckBestOdds-sider (hentet med fetch_cbo.py) og læg dem i SQLite.

Hver sæsonside indeholder alle japanske ligaer. J2-tabellen starter ved
<a name="J2 League"> og slutter ved næste <a name=...>.

Hver kamp-række ser sådan ud (forenklet):
  <tr>
    <td class="l2 match"><span ts="1708750800">..</span><a href="...">Yokohama FC -  Renofa Yamaguchi</a></td>
    <td class="r"><b class="">1.60</b></td>          <- odds hjemmesejr
    <td class="r"><b class="wygrana">4.00</b></td>   <- odds uafgjort ("wygrana" = vinder, polsk)
    <td class="r"><b class="">5.80</b></td>          <- odds udesejr
  </tr>

Oddsene er "the last highest odds we recorded for each of the bookmakers" –
IKKE Pinnacle-lukkeodds. Se README for forbehold.
"""
import sqlite3
from datetime import datetime, timezone

import pandas as pd
from bs4 import BeautifulSoup

DB = "data/j2.db"
SEASONS = [2022, 2023, 2024]

# CheckBestOdds-navn -> API-Football-navn. Fundet ved at sammenligne holdlisterne
# fra de to kilder. Navne, der er ens i begge kilder, står ikke her.
NAME_MAP = {
    "Albirex Niigata (JP)": "Albirex Niigata",
    "Ehime": "Ehime FC",
    "Fujieda": "Fujieda MYFC",
    "Ichihara Chiba": "JEF United Chiba",
    "Iwaki FC": "Iwaki",
    "Ryukyu": "FC Ryukyu",
    "Shimizu S-Pulse": "Shimizu S-pulse",
    "Thespa Kusatsu": "Thespakusatsu Gunma",
    "Tochigi": "Tochigi SC",
    "Tokushima": "Tokushima Vortis",
    "V-Varen Nagasaki": "V-varen Nagasaki",
    "Zweigen Kanazawa": "Kanazawa",
}


def j2_section(html):
    """Skær kun J2-tabellen ud af siden."""
    start = html.find('<a name="J2 League"></a>')
    end = html.find("<a name=", start + 10)
    if start == -1:
        raise ValueError("Fandt ikke J2 League på siden")
    return html[start:end]


def parse_season(season):
    with open(f"data/cbo/japan_{season}.html", encoding="utf-8") as f:
        soup = BeautifulSoup(j2_section(f.read()), "html.parser")

    rows = []
    for td in soup.select("td.match"):                    # én td.match pr. kamp
        tr = td.find_parent("tr")
        home, away = [x.strip() for x in td.a.get_text().split(" - ")]
        odds_cells = tr.select("td.r b")                    # de tre odds
        odds = [float(b.get_text()) for b in odds_cells]
        winner = [o for o, b in zip(["1", "X", "2"], odds_cells) if "wygrana" in b.get("class", [])]
        ts = int(td.span["ts"])
        rows.append({
            "season": season,
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
            "home": NAME_MAP.get(home, home),
            "away": NAME_MAP.get(away, away),
            "odds_1": odds[0], "odds_x": odds[1], "odds_2": odds[2],
            "winner": winner[0] if winner else None,
        })
    return pd.DataFrame(rows)


def main():
    df = pd.concat([parse_season(s) for s in SEASONS], ignore_index=True)

    con = sqlite3.connect(DB)
    df.to_sql("cbo_j2", con, if_exists="replace", index=False)

    # Kvalitetstjek 1: findes alle holdnavne også i API-dataene?
    api_teams = {r[0] for r in con.execute("SELECT home FROM matches UNION SELECT away FROM matches")}
    unknown = (set(df.home) | set(df.away)) - api_teams

    # Kvalitetstjek 2: passer vinderen hos CheckBestOdds med resultatet fra API'et?
    joined = pd.read_sql(
        """
        SELECT c.season, c.home, c.away, c.winner, m.home_goals, m.away_goals
        FROM cbo_j2 c
        JOIN matches m
          ON m.season = c.season AND m.home = c.home AND m.away = c.away
         AND m.round LIKE 'Regular Season%'
        """,
        con,
    )
    con.close()

    joined["api_winner"] = joined.apply(
        lambda r: "1" if r.home_goals > r.away_goals else "X" if r.home_goals == r.away_goals else "2", axis=1)
    mismatch = joined[joined.winner != joined.api_winner]

    print(f"{len(df)} J2-kampe med odds parset")
    print(df.groupby("season").size().to_string())
    print(f"Ukendte holdnavne: {sorted(unknown) if unknown else 'ingen'}")
    print(f"Koblet til API-resultater: {len(joined)} af {len(df)}")
    print(f"Vinder stemmer ikke overens: {len(mismatch)}")
    if len(mismatch):
        print(mismatch.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
