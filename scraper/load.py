"""Load scraped players JSON-lines into SQLite."""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("data/players.jsonl"))
    p.add_argument("--db", type=Path, default=Path("../db/bday-ballers.db"))
    p.add_argument("--schema", type=Path, default=Path("../db/schema.sql"))
    args = p.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.executescript(args.schema.read_text())

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    with args.input.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows.append((
                r["tm_id"], r["name"], r["date_of_birth"],
                r.get("position"), r.get("nationality"),
                r.get("current_club"), r.get("image_url"),
                r.get("profile_url"), r.get("last_seen_season"),
                r.get("height_cm"), r.get("foot"),
                r.get("place_of_birth_city"), r.get("place_of_birth_country"),
                r.get("national_team"), r.get("caps"), r.get("goals"),
                r.get("current_market_value_eur"),
                r.get("peak_market_value_eur"), r.get("peak_market_value_date"),
                now,
            ))

    conn.executemany("""
        INSERT INTO players
        (tm_id, name, date_of_birth, position, nationality, current_club,
         image_url, profile_url, last_seen_season,
         height_cm, foot, place_of_birth_city, place_of_birth_country,
         national_team, caps, goals,
         current_market_value_eur, peak_market_value_eur, peak_market_value_date,
         updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tm_id) DO UPDATE SET
            name=excluded.name,
            date_of_birth=excluded.date_of_birth,
            position=excluded.position,
            nationality=excluded.nationality,
            current_club=excluded.current_club,
            image_url=excluded.image_url,
            profile_url=excluded.profile_url,
            last_seen_season=excluded.last_seen_season,
            height_cm=excluded.height_cm,
            foot=excluded.foot,
            place_of_birth_city=excluded.place_of_birth_city,
            place_of_birth_country=excluded.place_of_birth_country,
            national_team=excluded.national_team,
            caps=excluded.caps,
            goals=excluded.goals,
            current_market_value_eur=excluded.current_market_value_eur,
            peak_market_value_eur=excluded.peak_market_value_eur,
            peak_market_value_date=excluded.peak_market_value_date,
            updated_at=excluded.updated_at
    """, rows)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    print(f"loaded {len(rows)} rows; total in DB: {n}")
    conn.close()


if __name__ == "__main__":
    main()
