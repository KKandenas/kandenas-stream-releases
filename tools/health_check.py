#!/usr/bin/env python3
"""Hälsokontroll för Kandenäs Stream: provar de inofficiella tjänsterna appen
använder, med samma anrop som appen. Om något har slutat fungera avslutas
skriptet med fel, och GitHub mejlar då om det misslyckade jobbet.

Körs varje vecka av .github/workflows/health.yml. Frågorna motsvarar dem i
appens kod (lib/sport/sport_sources.dart, lib/services/*_links.dart,
cloudflare/viaplay-proxy.js i det privata projektet). Ändras de där, ändra
här.
"""

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

APP = "https://kandenasstream.web.app"
ORIGIN = APP
USER_AGENT = "Mozilla/5.0 (KandenasStream hälsokontroll)"


def request(url, body=None, headers=None, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            **({"Content-Type": "application/json"} if data else {}),
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def config():
    return request(f"{APP}/sport_config.json")


def tv4(query, variables=None):
    version = config()["tv4ClientVersion"]
    data = request(
        "https://client-gateway.tv4.a2d.tv/graphql",
        {"query": query, **({"variables": variables} if variables else {})},
        {"client-name": "tv4-web", "client-version": version},
    )
    if data.get("errors"):
        raise AssertionError(f"TV4 svarade med fel: {data['errors'][0].get('message')} "
                             f"(klientversion {version} i sport_config.json)")
    return data["data"]


def svt(query):
    data = request("https://contento.svt.se/graphql", {"query": query})
    if data.get("errors"):
        raise AssertionError(f"SVT svarade med fel: {data['errors'][0].get('message')}")
    return data["data"]


JUSTWATCH_QUERY = """query S($q: String!) {
  popularTitles(country: SE, first: 20, filter: { searchQuery: $q }) {
    edges { node {
      objectType
      content(country: SE, language: "sv") {
        title originalTitle externalIds { tmdbId }
      }
      offers(country: SE, platform: WEB) {
        monetizationType standardWebURL package { packageId }
      }
    } }
  }
}"""


def justwatch_offers(data, tmdb_id):
    for edge in data["data"]["popularTitles"]["edges"]:
        node = edge["node"]
        if node["content"]["externalIds"]["tmdbId"] == str(tmdb_id):
            return {o["package"]["packageId"]: o["standardWebURL"] for o in node["offers"]}
    return {}


# ------------------------------------------------------------- kontrollerna


def check_tv4_sport():
    """Sport: TV4:s ligasidor (klientversionen i sport_config.json)."""
    data = tv4(
        '{ page(id: "allsvenskan") { content(input: {limit: 30, offset: 0}) { '
        "items { __typename ... on SportEventPanel { title "
        "content(input: {limit: 60, offset: 0}) { items { "
        "... on SportEventPanelItem { sportEvent { id title slug league "
        "isLiveContent playableFrom { isoString } liveEventEnd { isoString } "
        "} } } } } } } } }"
    )
    assert data["page"] is not None, "TV4:s sida allsvenskan finns inte"


def check_tv4_links():
    """Spela: TV4:s avsnitt till serie och sökning."""
    media = tv4('{ media(id: "022b4af1558ca550ab20") { ... on Episode { series { id slug } } } }')
    assert media["media"]["series"]["slug"] == "solsidan", f"Oväntat svar: {media}"
    search = tv4(
        "query($input: ListSearchInput!) { listSearch(input: $input) "
        "{ items { __typename ... on Series { id title slug } ... on Movie { id title slug } } } }",
        {"input": {"query": "Solsidan", "limit": 10, "offset": 0,
                   "includeUpsell": True, "types": ["SERIES"]}},
    )
    titles = [i.get("title") for i in search["listSearch"]["items"]]
    assert "Solsidan" in titles, f"TV4-sökningen hittade inte Solsidan: {titles}"


def check_svt_sport():
    """Sport: SVT:s kommande sändningar."""
    data = svt(
        '{ categoryPage(id: "sport", filter: {userIsAbroad: false, '
        "onlyKidsContent: false, kidsFilter: false}) { "
        'lazyLoadedTabs(slug: "upcoming") { slug modules { id '
        "calendarSelection { items { heading subHeading liveNow "
        "item { urls { svtplay } } } } } } } }"
    )
    assert data["categoryPage"] is not None, "SVT:s sportsida finns inte"


def check_svt_links():
    """Spela: SVT:s programsidor och sökning."""
    page = svt('{ detailsPageByPath(path: "/the-office") { item { id urls { svtplay } } } }')
    assert page["detailsPageByPath"]["item"]["id"], f"Oväntat svar: {page}"
    search = svt('{ search(query: "The Office") { item { __typename ... on TvSeries { id name } } } }')
    names = [h["item"].get("name") for h in search["search"]]
    assert "The Office" in names, f"SVT-sökningen hittade inte The Office: {names}"


def check_justwatch():
    """Spela: JustWatchs direktlänkar (Android frågar direkt)."""
    data = request("https://apis.justwatch.com/graphql",
                   {"query": JUSTWATCH_QUERY, "variables": {"q": "The Last of Us"}})
    offers = justwatch_offers(data, 100088)
    assert 1899 in offers, f"JustWatch saknar HBO Max-länken för The Last of Us: {offers}"


def check_worker():
    """Webben: Cloudflare-mellanhanden (JustWatch och Viaplay-sport)."""
    proxy = config()["viaplayProxy"].rstrip("/")
    data = request(f"{proxy}/justwatch?q=" + urllib.parse.quote("Barbie"), headers={"Origin": ORIGIN})
    assert justwatch_offers(data, 346698), "Mellanhanden gav inga JustWatch-länkar för Barbie"
    viaplay = request(f"{proxy}/pc-se/sport/fotboll/uefa-champions-league", headers={"Origin": ORIGIN})
    assert viaplay.get("_embedded") or viaplay.get("title"), "Mellanhanden gav inget Viaplay-svar"


def check_viaplay():
    """Sport: Viaplays innehålls-API (Android frågar direkt)."""
    data = request("https://content.viaplay.se/pc-se/sport/fotboll/uefa-champions-league")
    assert data.get("_embedded") or data.get("title"), "Viaplay gav ett oväntat svar"


def check_imdb():
    """IMDb-betygen: filen ska vara högst tio dagar gammal."""
    data = request("https://raw.githubusercontent.com/KKandenas/kandenas-stream-releases/main/imdb.json")
    updated = datetime.date.fromisoformat(data["updated"])
    age = (datetime.date.today() - updated).days
    assert age <= 10, f"imdb.json är {age} dagar gammal (uppdaterad {updated}). Kör IMDb-jobbet."
    assert len(data["movie"]) > 10000, "imdb.json har för få filmer"


CHECKS = [
    check_tv4_sport,
    check_tv4_links,
    check_svt_sport,
    check_svt_links,
    check_justwatch,
    check_worker,
    check_viaplay,
    check_imdb,
]


def main():
    lines = []
    failed = 0
    for check in CHECKS:
        name = check.__doc__.strip().splitlines()[0]
        try:
            check()
            lines.append(f"✅ {name}")
        except Exception as e:  # noqa: BLE001 – rapportera och fortsätt
            failed += 1
            lines.append(f"❌ {name}\n   {type(e).__name__}: {e}")
    report = "\n".join(lines)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Hälsokontroll\n\n" + report.replace("\n   ", "\n\n    ") + "\n")
    if failed:
        sys.exit(f"{failed} av {len(CHECKS)} kontroller misslyckades.")


if __name__ == "__main__":
    main()
