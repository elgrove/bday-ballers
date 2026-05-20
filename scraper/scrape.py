"""Transfermarkt scraper for Bday Ballers.

Three phases:
  1. Discover clubs from competition pages (across seasons).
  2. Discover player profile URLs from each club-season page.
  3. Fetch each unique player profile and extract attributes.

HTML is cached on disk by URL hash so re-runs are free and parser tweaks
do not require re-fetching. Output is JSON-lines, one record per player.
"""

import argparse
import hashlib
import json
import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from competitions import COMPETITIONS

BASE = "https://www.transfermarkt.com"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scrape")


class Scraper:
    def __init__(self, cache_dir: Path, rate: float = 0.4, jitter: float = 0.3):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rate = rate
        self.jitter = jitter
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-GB,en;q=0.9",
        })
        self._last_fetch = 0.0
        self._rate_lock = threading.Lock()

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.html"

    def _wait_turn(self):
        # Serialise the *start* of fetches so we never exceed 1/rate req/sec
        # globally, regardless of how many worker threads are calling in.
        with self._rate_lock:
            elapsed = time.time() - self._last_fetch
            wait = max(0.0, self.rate - elapsed) + random.uniform(0, self.jitter)
            if wait > 0:
                time.sleep(wait)
            self._last_fetch = time.time()

    def fetch(self, url: str) -> str:
        cache_path = self._cache_path(url)
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        last_err: Exception | None = None
        for attempt in range(4):
            self._wait_turn()
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    cache_path.write_text(resp.text, encoding="utf-8")
                    return resp.text
                if resp.status_code in (429, 503):
                    backoff = (2 ** attempt) * 5
                    log.warning("status %d on %s, sleeping %ds", resp.status_code, url, backoff)
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
            except requests.RequestException as e:
                last_err = e
                log.warning("attempt %d failed for %s: %s", attempt + 1, url, e)
                time.sleep(2 ** attempt)
        raise RuntimeError(f"failed to fetch {url}: {last_err}")


def comp_url(comp_id: str, slug: str, season: int) -> str:
    return f"{BASE}/{slug}/startseite/wettbewerb/{comp_id}/plus/?saison_id={season}"


def club_url(slug: str, club_id: str, season: int) -> str:
    return f"{BASE}/{slug}/startseite/verein/{club_id}/saison_id/{season}"


def player_url(slug: str, player_id: str) -> str:
    return f"{BASE}/{slug}/profil/spieler/{player_id}"


def mv_api_url(player_id: str) -> str:
    return f"{BASE}/ceapi/marketValueDevelopment/graph/{player_id}"


def parse_clubs(html: str) -> list[tuple[str, str]]:
    """Return unique (club_id, slug) pairs from a competition page."""
    soup = BeautifulSoup(html, "lxml")
    clubs: dict[str, str] = {}
    for a in soup.select("a[href*='/startseite/verein/']"):
        href = a.get("href", "")
        m = re.match(r"/([^/]+)/startseite/verein/(\d+)", href)
        if m:
            clubs[m.group(2)] = m.group(1)
    return list(clubs.items())


def parse_players(html: str) -> list[tuple[str, str]]:
    """Return unique (player_id, slug) pairs from a club page."""
    soup = BeautifulSoup(html, "lxml")
    players: dict[str, str] = {}
    for a in soup.select("a[href*='/profil/spieler/']"):
        href = a.get("href", "")
        m = re.match(r"/([^/]+)/profil/spieler/(\d+)", href)
        if m:
            players[m.group(2)] = m.group(1)
    return list(players.items())


def parse_dob(text: str) -> str | None:
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text.strip()).strip()
    for fmt in ("%b %d, %Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _extract_info_table(soup: BeautifulSoup):
    """Return (label -> str) and (label -> bs4 element) for value cells."""
    data: dict[str, str] = {}
    raw: dict[str, "object"] = {}
    spans = soup.select(".info-table span.info-table__content")
    i = 0
    while i < len(spans) - 1:
        a, b = spans[i], spans[i + 1]
        a_cls = a.get("class", [])
        b_cls = b.get("class", [])
        if "info-table__content--regular" in a_cls and "info-table__content--bold" in b_cls:
            label = a.get_text(" ", strip=True).rstrip(":").strip().lower()
            value = b.get_text(" ", strip=True)
            if label:
                data[label] = value
                raw[label] = b
            i += 2
        else:
            i += 1
    return data, raw


def _extract_nationalities(value_el) -> str | None:
    """Comma-separated list of countries, taken from flag image titles."""
    if value_el is None:
        return None
    flags = value_el.select("img.flaggenrahmen")
    countries = [f.get("title") for f in flags if f.get("title")]
    if countries:
        return ", ".join(countries)
    text = value_el.get_text(" ", strip=True)
    return text or None


def parse_money(text: str | None) -> int | None:
    """Parse '€10.00m', '€ 10.00 m', '€500k', '€100Th.', etc. into euros."""
    if not text:
        return None
    s = text.replace("\xa0", " ").strip().lower()
    s = s.replace("€", "").replace("eur", "").strip()
    if not s or s in {"-", "?", "n/a"}:
        return None
    m = re.match(r"([\d.,]+)\s*([a-zäöü.]*)", s)
    if not m:
        return None
    num_str = m.group(1).replace(",", ".")
    try:
        num = float(num_str)
    except ValueError:
        return None
    unit = m.group(2)
    if unit.startswith("m") or "mio" in unit:
        return int(round(num * 1_000_000))
    if unit.startswith("k") or unit.startswith("th") or "tsd" in unit:
        return int(round(num * 1_000))
    return int(round(num))


def parse_height_cm(text: str | None) -> int | None:
    """Parse '1,81 m' / '1.81\xa0m' / '181 cm' into integer centimetres."""
    if not text:
        return None
    s = text.replace("\xa0", " ").strip().lower()
    m = re.match(r"([\d.,]+)\s*m\b", s)
    if m:
        try:
            return int(round(float(m.group(1).replace(",", ".")) * 100))
        except ValueError:
            return None
    m = re.match(r"([\d.,]+)\s*cm\b", s)
    if m:
        try:
            return int(round(float(m.group(1).replace(",", "."))))
        except ValueError:
            return None
    return None


def _extract_place_of_birth(value_el):
    """Return (city, country) from a 'Place of birth' info-table cell."""
    if value_el is None:
        return None, None
    flag = value_el.select_one("img.flaggenrahmen")
    country = flag.get("title") if flag else None
    # City text excludes the flag's title attribute (BS4 .get_text already
    # ignores attributes). Watch out for value cells that are empty.
    text = value_el.get_text(" ", strip=True)
    city = text or None
    return city, country


def _extract_caps_goals(soup):
    """Return (national_team, caps, goals) from the data-header items list."""
    team = caps = goals = None
    items = soup.select(".data-header__items li")
    for li in items:
        text = li.get_text(" ", strip=True)
        if text.lower().startswith("current international"):
            team = text.split(":", 1)[-1].strip() or None
        elif text.lower().startswith("caps/goals"):
            tail = text.split(":", 1)[-1].strip()
            m = re.match(r"(\d+)\s*/\s*(\d+)", tail)
            if m:
                caps = int(m.group(1))
                goals = int(m.group(2))
    return team, caps, goals


def _extract_current_market_value(soup) -> int | None:
    el = soup.select_one(".data-header__market-value-wrapper")
    if not el:
        return None
    text = el.get_text(" ", strip=True)
    # Format: "€ 10.00 m Last update: 24/03/2026". Take the leading money.
    m = re.match(r"(€\s*[\d.,]+\s*[a-zA-Z.]*)", text)
    return parse_money(m.group(1)) if m else None


def parse_player(html: str, tm_id: str, profile_url: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    name_el = soup.select_one("h1.data-header__headline-wrapper") or soup.select_one("h1")
    name = name_el.get_text(" ", strip=True) if name_el else None
    if name:
        name = re.sub(r"^#\d+\s*", "", name).strip()

    img_el = soup.select_one("img.data-header__profile-image")
    image_url = img_el.get("src") if img_el else None

    data, raw = _extract_info_table(soup)

    dob_raw = None
    for key in ("date of birth", "date of birth/age", "born", "geb./alter"):
        if key in data:
            dob_raw = data[key]
            break
    if not dob_raw:
        bday = soup.select_one("a[href*='/geburtstag/']")
        if bday:
            dob_raw = bday.get_text(" ", strip=True)

    dob = parse_dob(dob_raw) if dob_raw else None
    if not dob or not name:
        log.debug("skip %s: name=%r dob_raw=%r", tm_id, name, dob_raw)
        return None

    nationality = _extract_nationalities(raw.get("citizenship") or raw.get("nationality"))
    pob_city, pob_country = _extract_place_of_birth(raw.get("place of birth"))
    height_cm = parse_height_cm(data.get("height"))
    foot = (data.get("foot") or "").strip().lower() or None
    nat_team, caps, goals = _extract_caps_goals(soup)
    current_mv = _extract_current_market_value(soup)

    return {
        "tm_id": tm_id,
        "name": name,
        "date_of_birth": dob,
        "position": data.get("position"),
        "nationality": nationality,
        "current_club": data.get("current club"),
        "image_url": image_url,
        "profile_url": profile_url,
        "height_cm": height_cm,
        "foot": foot,
        "place_of_birth_city": pob_city,
        "place_of_birth_country": pob_country,
        "national_team": nat_team,
        "caps": caps,
        "goals": goals,
        "current_market_value_eur": current_mv,
    }


def run(competitions, seasons, output: Path, cache_dir: Path, workers: int = 4):
    sc = Scraper(cache_dir)

    log.info("phase 1: %d competitions × %d seasons", len(competitions), len(seasons))
    club_seasons: set[tuple[str, str, int]] = set()
    for comp_id, comp_slug in competitions:
        for season in seasons:
            try:
                html = sc.fetch(comp_url(comp_id, comp_slug, season))
            except Exception as e:
                log.warning("comp %s season %d failed: %s", comp_id, season, e)
                continue
            clubs = parse_clubs(html)
            log.info("comp %s season %d: %d clubs", comp_id, season, len(clubs))
            for club_id, slug in clubs:
                club_seasons.add((club_id, slug, season))

    log.info("phase 2: %d club-seasons", len(club_seasons))
    player_seasons: dict[str, tuple[str, int]] = {}
    p2_lock = threading.Lock()

    def fetch_club(item):
        club_id, slug, season = item
        try:
            html = sc.fetch(club_url(slug, club_id, season))
        except Exception as e:
            log.warning("club %s/%d failed: %s", club_id, season, e)
            return []
        return [(pid, pslug, season) for pid, pslug in parse_players(html)]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for found in ex.map(fetch_club, sorted(club_seasons)):
            with p2_lock:
                for pid, pslug, season in found:
                    existing = player_seasons.get(pid)
                    if not existing or season > existing[1]:
                        player_seasons[pid] = (pslug, season)

    log.info("phase 3: %d unique players", len(player_seasons))
    output.parent.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()
    counts = {"written": 0, "skipped": 0}

    def fetch_player(item):
        pid, slug, last_season = item
        url = player_url(slug, pid)
        try:
            html = sc.fetch(url)
        except Exception as e:
            log.warning("player %s failed: %s", pid, e)
            return None
        record = parse_player(html, pid, url)
        if not record:
            return None
        record["last_seen_season"] = last_season

        try:
            mv_text = sc.fetch(mv_api_url(pid))
            mv = json.loads(mv_text)
            record["peak_market_value_eur"] = parse_money(mv.get("highest"))
            record["peak_market_value_date"] = mv.get("highest_date")
            # Prefer API current-value if profile page didn't yield one.
            if record.get("current_market_value_eur") is None:
                record["current_market_value_eur"] = parse_money(mv.get("current"))
        except Exception as e:
            log.warning("mv api %s failed: %s", pid, e)
            record["peak_market_value_eur"] = None
            record["peak_market_value_date"] = None

        return record

    items = [(pid, slug, season) for pid, (slug, season) in player_seasons.items()]
    with output.open("w", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(fetch_player, item) for item in items]
        progress_step = max(1, len(futures) // 50)
        for i, fut in enumerate(as_completed(futures), 1):
            record = fut.result()
            with write_lock:
                if record is None:
                    counts["skipped"] += 1
                else:
                    f.write(json.dumps(record) + "\n")
                    counts["written"] += 1
            if i % progress_step == 0:
                log.info("phase 3 progress: %d/%d", i, len(futures))

    log.info("done: wrote %d, skipped %d", counts["written"], counts["skipped"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--competitions", nargs="*", help="comp IDs (default: all in competitions.py)")
    p.add_argument("--season-from", type=int, default=2000)
    p.add_argument("--season-to", type=int, default=2024)
    p.add_argument("--cache-dir", type=Path, default=Path("cache"))
    p.add_argument("--output", type=Path, default=Path("data/players.jsonl"))
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    if args.competitions:
        wanted = set(args.competitions)
        comps = [(cid, slug) for cid, slug in COMPETITIONS if cid in wanted]
    else:
        comps = COMPETITIONS

    seasons = range(args.season_from, args.season_to + 1)
    run(comps, seasons, args.output, args.cache_dir, workers=args.workers)


if __name__ == "__main__":
    main()
