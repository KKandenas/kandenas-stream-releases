#!/usr/bin/env python3
"""Bygger imdb.json för Kandenäs Stream: IMDb-betyg per TMDB-id och egna
topplistor för filmer och serier.

Körs varje vecka av .github/workflows/imdb.yml.

Källor:
- IMDb:s datafiler (https://datasets.imdbws.com, för privat och icke-
  kommersiellt bruk): betyg och antal röster per IMDb-id.
- Wikidata: vilket TMDB-id (film P4947, serie P4983) ett IMDb-id (P345)
  hör till. Frågas via QLever (en snabb kopia av Wikidata), med Wikidatas
  egen tjänst som reserv. Den avbryter ofta så stora frågor från GitHub.

Format (kompakt, appen läser det i lib/services/imdb_ratings.dart):
{
  "updated": "2026-10-08",
  "movie": {"550": [88, 2400]},   # TMDB-id: [betyg x10, röster i tusental]
  "tv":    {"1399": [92, 2300]},
  "top":   {"movie": [278, 238, ...], "tv": [...]}   # TMDB-id, bäst först
}
"""

import csv
import datetime
import gzip
import io
import json
import sys
import time
import urllib.parse
import urllib.request

RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
# Först QLever, sedan Wikidata.
SPARQL_ENDPOINTS = [
    "https://qlever.dev/api/wikidata",
    "https://query.wikidata.org/sparql",
]
USER_AGENT = "KandenasStream/1.0 (https://github.com/KKandenas/kandenas-stream-releases)"

# Färre röster än så: betyget säger för lite och tar bara plats.
MIN_VOTES = 500
# Som IMDb:s Top 250: viktat betyg, med minsta antal röster för att komma med.
TOP_MIN_VOTES = 25000
TOP_SIZE = 250


def fetch(url, headers=None, timeout=300):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def imdb_ratings():
    """IMDb-id -> (betyg, röster)."""
    data = gzip.decompress(fetch(RATINGS_URL))
    reader = csv.reader(io.StringIO(data.decode("utf-8")), delimiter="\t")
    next(reader)
    ratings = {}
    for tconst, rating, votes in reader:
        votes = int(votes)
        if votes >= MIN_VOTES:
            ratings[tconst] = (float(rating), votes)
    return ratings


def wikidata_mapping(tmdb_property):
    """IMDb-id -> TMDB-id för filmer (P4947) eller serier (P4983)."""
    query = (
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
        f"SELECT ?imdb ?tmdb WHERE {{ ?i wdt:{tmdb_property} ?tmdb ; wdt:P345 ?imdb . }}"
    )
    errors = []
    for endpoint in SPARQL_ENDPOINTS:
        for attempt in range(3):
            try:
                url = endpoint + "?" + urllib.parse.urlencode({"query": query})
                text = fetch(url, {"Accept": "text/csv"}).decode("utf-8")
                return _parse_mapping(text)
            except Exception as e:  # noqa: BLE001 – nästa försök eller tjänst
                errors.append(f"{endpoint} försök {attempt + 1}: {e}")
                time.sleep(10)
    sys.exit("Kunde inte hämta kopplingen IMDb–TMDB:\n" + "\n".join(errors))


def _parse_mapping(text):
    """Kastar ValueError för ofullständiga svar (avbruten fråga)."""
    reader = csv.reader(io.StringIO(text))
    if next(reader, None) != ["imdb", "tmdb"]:
        raise ValueError("oväntat svar")
    mapping = {}
    for row in reader:
        if len(row) != 2:
            raise ValueError(f"ofullständig rad: {row!r}"[:200])
        imdb, tmdb = row
        if imdb.startswith("tt") and tmdb.isdigit():
            # Första vinner om ett IMDb-id har flera TMDB-id.
            mapping.setdefault(imdb, int(tmdb))
    if len(mapping) < 1000:
        raise ValueError(f"bara {len(mapping)} kopplingar")
    return mapping


def build(ratings, mapping):
    """TMDB-id -> [betyg x10, röster i tusental] och topplistan."""
    by_tmdb = {}
    for imdb, tmdb in mapping.items():
        if imdb in ratings and tmdb not in by_tmdb:
            by_tmdb[tmdb] = ratings[imdb]

    # IMDb:s formel: viktat betyg mot medelbetyget bland titlarna.
    mean = sum(r for r, _ in by_tmdb.values()) / max(len(by_tmdb), 1)
    m = TOP_MIN_VOTES

    def weighted(item):
        rating, votes = item[1]
        return votes / (votes + m) * rating + m / (votes + m) * mean

    top = sorted(
        ((tmdb, rv) for tmdb, rv in by_tmdb.items() if rv[1] >= TOP_MIN_VOTES),
        key=weighted,
        reverse=True,
    )[:TOP_SIZE]

    compact = {
        str(tmdb): [round(rating * 10), round(votes / 1000)]
        for tmdb, (rating, votes) in by_tmdb.items()
    }
    return compact, [tmdb for tmdb, _ in top]


def main(out_path):
    ratings = imdb_ratings()
    movies, movie_top = build(ratings, wikidata_mapping("P4947"))
    shows, tv_top = build(ratings, wikidata_mapping("P4983"))

    # Skydd mot ett trasigt svar: hellre förra veckans fil än en tom.
    if len(movies) < 10000 or len(shows) < 2000:
        sys.exit(f"För få titlar ({len(movies)} filmer, {len(shows)} serier), sparar inte.")

    result = {
        "updated": datetime.date.today().isoformat(),
        "movie": movies,
        "tv": shows,
        "top": {"movie": movie_top, "tv": tv_top},
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, separators=(",", ":"), sort_keys=True)
    print(f"{len(movies)} filmer, {len(shows)} serier, topplistor {len(movie_top)}/{len(tv_top)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "imdb.json")
