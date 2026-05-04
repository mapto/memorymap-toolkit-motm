import requests
from urllib.parse import urlparse
import regex as re


GEONAMES_USERNAME = "mapto"

domains = ["geonames.org", "wikidata.org"]


def search_location(query, max_rows=10):
    url = "http://api.geonames.org/searchJSON"
    params = {"q": query, "maxRows": max_rows, "username": GEONAMES_USERNAME}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def extract_url_map(text: str) -> tuple[dict[str, str], str]:
    pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(pattern, text)
    url_map = {urlparse(u).hostname: u for u in urls}
    remaining = re.sub(pattern, "", text).strip()
    return url_map, remaining.strip()


def extract_urls(text: str) -> list[tuple[str, dict[str, str]]]:
    """
    >>> extract_urls("Allenstein")
    [('Allenstein', {})]
    """
    pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'

    # Normalize: treat newlines as spaces
    text = text.replace("\n", " ")

    parts = re.split(pattern, text)
    urls = re.findall(pattern, text)

    pairs: list[tuple[str, dict[str, str]]] = []
    for i, substring in enumerate(parts):
        substring = substring.strip()
        if i < len(urls):
            adjacent_urls: list[str] = [urls[i]]
            while i + 1 < len(urls) and parts[i + 1].strip() == "":
                i += 1
                adjacent_urls += [urls[i]]
            url_map = {}
            for u in adjacent_urls:
                h = urlparse(u).hostname
                # assert h not in url_map, f"{h} repeated in {urls}"
                if h not in url_map:
                    url_map[h] = []
                url_map[h] += [u]
            pairs += [(substring, {k: " | ".join(v) for k, v in url_map.items()})]
        elif substring:
            pairs += [(substring, {})]

    return pairs


def extract_geonames_coordinates(url: str) -> dict | None:
    """
    Extract coordinates from a GeoNames entity URL.
    e.g. https://www.geonames.org/6550600/finsterwalde.html

    Fetches the entity via the GeoNames API using the numeric ID.
    Returns dict with 'lat' and 'lng', or None if not found.

    Requires a free GeoNames account username: https://www.geonames.org/login
    """
    match = re.search(r"geonames\.org/(\d+)", url)
    if not match:
        return None

    geoname_id = match.group(1)

    response = requests.get(
        "http://api.geonames.org/getJSON",
        params={"geonameId": geoname_id, "username": GEONAMES_USERNAME},
        headers={"User-Agent": "coord-extractor/1.0"},
    )
    response.raise_for_status()
    data = response.json()

    try:
        return {"lat": float(data["lat"]), "long": float(data["lng"])}
    except (KeyError, ValueError):
        return None


def extract_wikidata_coordinates(url: str) -> dict | None:
    """
    Extract coordinates from a Wikidata entity URL.
    e.g. https://www.wikidata.org/wiki/Q64

    Fetches the entity via the Wikidata API and reads property P625 (coordinate location).
    Returns dict with 'lat' and 'lng', or None if not found.
    """
    match = re.search(r"/wiki/(Q\d+)", url)
    if not match:
        return None

    qid = match.group(1)

    response = requests.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbgetentities",
            "ids": qid,
            "props": "claims",
            "format": "json",
        },
        headers={"User-Agent": "coord-extractor/1.0"},
    )
    response.raise_for_status()
    data = response.json()

    try:
        claims = data["entities"][qid]["claims"]
        p625 = claims["P625"][0]["mainsnak"]["datavalue"]["value"]
        return {"lat": p625["latitude"], "long": p625["longitude"]}
    except (KeyError, IndexError):
        return None


"""
# locs = {n:l for l, n in df["location"].apply(lambda x: extract_urls(x)).to_list()}
locs = {}
for row in tqdm(df["location"]):
    # print(row)
    # print(extract_urls(row))
    for name, urls in extract_urls(row):
        urls["location"] = name
        
        coords = {}
        if "www.geonames.org" in urls:
            coords = extract_geonames_coordinates(urls["www.geonames.org"])
        elif "www.wikidata.org" in urls:
            coords = extract_wikidata_coordinates(urls["www.wikidata.org"])

        print(urls)
        print(coords)
        print()
        urls |= coords
        locs[name] = urls
print(locs)    
# pd.DataFrame.from_dict(locs, orient="index").to_excel("locations.xlsx")
# rows = []
# for k, v in locs.items():
#     coords = None
#     if "www.geonames.org" in 
#     coords = extract_geonames_coordinates(
#     rows += [{
#         "location": k,
#         "lat"
#     } | v]
pd.DataFrame(rows).to_excel("locations.xlsx", index=False)
"""
