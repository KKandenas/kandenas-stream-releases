# Kandenäs Stream – releaser och data

Publikt projekt med det appen hämtar. Koden finns i det privata projektet
`kandenas-stream`.

- **Releaser**: Android-appen (`kandenas.apk` och `version.json`). Appen
  uppdaterar sig själv härifrån. Första installationen: hämta
  `https://github.com/KKandenas/kandenas-stream-releases/releases/latest/download/kandenas.apk`
  med appen Downloader.
- **imdb.json**: IMDb-betyg per TMDB-id och egna topplistor (samma formel
  som IMDb:s Top 250). Byggs varje måndag av `.github/workflows/imdb.yml`
  med `tools/build_imdb.py`, från IMDb:s datafiler
  (https://datasets.imdbws.com, för privat och icke-kommersiellt bruk) och
  Wikidata. Kan köras för hand under Actions → IMDb-betyg → Run workflow.
- **Hälsokontroll**: `.github/workflows/health.yml` provar varje tisdag med
  `tools/health_check.py` att de inofficiella tjänsterna appen använder
  fungerar (TV4, SVT, Viaplay, JustWatch, Cloudflare-mellanhanden och att
  imdb.json är färsk). Misslyckas något mejlar GitHub, och sammanfattningen
  under Actions visar vad.
