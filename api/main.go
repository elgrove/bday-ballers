// Bday Ballers HTTP server.
//
// Serves a single JSON endpoint and the static frontend from one binary so
// deployment is a single systemd unit.

package main

import (
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	_ "modernc.org/sqlite"
)

type Player struct {
	TMID                  string  `json:"tm_id"`
	Name                  string  `json:"name"`
	DateOfBirth           string  `json:"date_of_birth"`
	DaysOff               int     `json:"days_off"`
	Position              *string `json:"position"`
	Nationality           *string `json:"nationality"`
	CurrentClub           *string `json:"current_club"`
	ImageURL              *string `json:"image_url"`
	ProfileURL            *string `json:"profile_url"`
	HeightCM              *int    `json:"height_cm"`
	Foot                  *string `json:"foot"`
	PlaceOfBirthCity      *string `json:"place_of_birth_city"`
	PlaceOfBirthCountry   *string `json:"place_of_birth_country"`
	NationalTeam          *string `json:"national_team"`
	Caps                  *int    `json:"caps"`
	Goals                 *int    `json:"goals"`
	CurrentMarketValueEUR *int64  `json:"current_market_value_eur"`
	PeakMarketValueEUR    *int64  `json:"peak_market_value_eur"`
	PeakMarketValueDate   *string `json:"peak_market_value_date"`
	LastSeenSeason        *int    `json:"last_seen_season"`
}

type Response struct {
	Query   QueryEcho `json:"query"`
	Results []Player  `json:"results"`
}

type QueryEcho struct {
	DateOfBirth string `json:"date_of_birth"`
	Limit       int    `json:"limit"`
}

// Hard window in days either side of the user's DOB — past this, players
// aren't "born when you were" no matter how famous.
const windowDays = 30

// Notability score within the window: peak_mv * (1 + caps/30) / (1 + days_off/14).
// Players with no peak market value are excluded — without that signal we
// can't rank them at all.
const rankQuery = `
SELECT tm_id, name, date_of_birth, position, nationality, current_club,
       image_url, profile_url, height_cm, foot,
       place_of_birth_city, place_of_birth_country,
       national_team, caps, goals, last_seen_season,
       current_market_value_eur, peak_market_value_eur, peak_market_value_date,
       CAST(ROUND(ABS(julianday(date_of_birth) - julianday(?1))) AS INTEGER) AS days_off
FROM players
WHERE peak_market_value_eur IS NOT NULL
  AND ABS(julianday(date_of_birth) - julianday(?1)) <= ?2
ORDER BY (
    CAST(peak_market_value_eur AS REAL)
    * (1.0 + COALESCE(caps, 0) / 30.0)
    / (1.0 + ABS(julianday(date_of_birth) - julianday(?1)) / 14.0)
) DESC
LIMIT ?3`

func main() {
	dbPath := flag.String("db", "../db/bday-ballers.db", "path to SQLite DB")
	webDir := flag.String("web", "../web", "path to static frontend")
	addr := flag.String("addr", ":8080", "listen address")
	flag.Parse()

	abs, _ := filepath.Abs(*dbPath)
	db, err := sql.Open("sqlite", abs+"?mode=ro&_pragma=journal_mode(WAL)")
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer db.Close()
	if err := db.Ping(); err != nil {
		log.Fatalf("ping db: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/api/players", handlePlayers(db))
	mux.HandleFunc("/api/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("ok\n"))
	})
	mux.Handle("/", http.FileServer(http.Dir(*webDir)))

	srv := &http.Server{
		Addr:              *addr,
		Handler:           logRequests(mux),
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("listening on %s (db=%s, web=%s)", *addr, abs, *webDir)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}

func handlePlayers(db *sql.DB) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		dob := r.URL.Query().Get("dob")
		if _, err := time.Parse("2006-01-02", dob); err != nil {
			httpError(w, http.StatusBadRequest, "dob must be YYYY-MM-DD")
			return
		}
		limit := 10
		if s := r.URL.Query().Get("limit"); s != "" {
			n, err := strconv.Atoi(s)
			if err != nil || n < 1 || n > 100 {
				httpError(w, http.StatusBadRequest, "limit must be 1..100")
				return
			}
			limit = n
		}

		rows, err := db.QueryContext(r.Context(), rankQuery, dob, windowDays, limit)
		if err != nil {
			log.Printf("query: %v", err)
			httpError(w, http.StatusInternalServerError, "query failed")
			return
		}
		defer rows.Close()

		players := make([]Player, 0, limit)
		for rows.Next() {
			var p Player
			if err := rows.Scan(
				&p.TMID, &p.Name, &p.DateOfBirth,
				&p.Position, &p.Nationality, &p.CurrentClub,
				&p.ImageURL, &p.ProfileURL,
				&p.HeightCM, &p.Foot,
				&p.PlaceOfBirthCity, &p.PlaceOfBirthCountry,
				&p.NationalTeam, &p.Caps, &p.Goals,
				&p.LastSeenSeason,
				&p.CurrentMarketValueEUR, &p.PeakMarketValueEUR, &p.PeakMarketValueDate,
				&p.DaysOff,
			); err != nil {
				log.Printf("scan: %v", err)
				httpError(w, http.StatusInternalServerError, "scan failed")
				return
			}
			players = append(players, p)
		}
		if err := rows.Err(); err != nil && !errors.Is(err, sql.ErrNoRows) {
			log.Printf("rows: %v", err)
		}

		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		w.Header().Set("Cache-Control", "public, max-age=300")
		json.NewEncoder(w).Encode(Response{
			Query:   QueryEcho{DateOfBirth: dob, Limit: limit},
			Results: players,
		})
	}
}

func httpError(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		log.Printf("%s %s %s (%s)", r.RemoteAddr, r.Method, r.URL.Path, time.Since(start))
	})
}

// silence unused-import lint when running with -tags=netgo on older toolchains
var _ = os.Getenv
