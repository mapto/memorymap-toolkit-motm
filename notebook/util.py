import requests
from urllib.parse import urlparse

import regex as re


GEONAMES_USERNAME = "mapto"

domains = ["geonames.org", "wikidata.org"]

def search_location(query, max_rows=10):
    url = "http://api.geonames.org/searchJSON"
    params = {
        "q": query,
        "maxRows": max_rows,
        "username": GEONAMES_USERNAME
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def extract_url_map(text:str)-> tuple[dict[str,str],str]:
    pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(pattern, text)
    url_map = {urlparse(u).hostname: u for u in urls}
    remaining = re.sub(pattern, "", text).strip()
    return url_map, remaining.strip()

def extract_urls(text: str) -> list[tuple[str, dict[str,str]]]:
    """
    >>> extract_urls("Allenstein")
    [('Allenstein', {})]
    """
    pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'

    # Normalize: treat newlines as spaces
    text = text.replace("\n", " ")
    
    parts = re.split(pattern, text)
    urls = re.findall(pattern, text)

    pairs: list[tuple[str, dict[str,str]]] = []
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
            pairs += [(substring, {k: " | ".join(v) for k,v in url_map.items()})]
        elif substring:
            pairs += [(substring, {})]

    return pairs