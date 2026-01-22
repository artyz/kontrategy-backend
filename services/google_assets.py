import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

def google_image_thumbnails(instagram_username: str, limit: int = 15):
    """
    Devuelve thumbnails públicos de Google Images
    relacionados con un perfil de Instagram
    """
    query = f'instagram "{instagram_username}"'
    url = (
        "https://www.google.com/search?"
        f"q={quote_plus(query)}"
        "&tbm=isch"
        "&hl=es"
    )

    res = requests.get(url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(res.text, "html.parser")

    images = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and src.startswith("http"):
            images.append(src)
        if len(images) >= limit:
            break

    return images


def google_search_snippets(instagram_username: str, limit: int = 10):
    """
    Devuelve títulos y descripciones de Google Search
    """
    query = f'instagram "{instagram_username}"'
    url = f"https://www.google.com/search?q={quote_plus(query)}&hl=es"

    res = requests.get(url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []

    for result in soup.select("div.g"):
        title = result.find("h3")
        snippet = result.find("div", class_="VwiC3b")

        if title and snippet:
            results.append({
                "title": title.text,
                "snippet": snippet.text
            })

        if len(results) >= limit:
            break

    return results

