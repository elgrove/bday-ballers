CREATE TABLE IF NOT EXISTS players (
    tm_id                    TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    date_of_birth            TEXT NOT NULL,
    position                 TEXT,
    nationality              TEXT,
    current_club             TEXT,
    image_url                TEXT,
    profile_url              TEXT,
    last_seen_season         INTEGER,
    height_cm                INTEGER,
    foot                     TEXT,
    place_of_birth_city      TEXT,
    place_of_birth_country   TEXT,
    national_team            TEXT,
    caps                     INTEGER,
    goals                    INTEGER,
    current_market_value_eur INTEGER,
    peak_market_value_eur    INTEGER,
    peak_market_value_date   TEXT,
    updated_at               TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_players_dob ON players(date_of_birth);
CREATE INDEX IF NOT EXISTS idx_players_peak_mv ON players(peak_market_value_eur);
