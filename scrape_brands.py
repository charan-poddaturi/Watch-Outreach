import csv
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
IGNORE_DOMAINS = ("sentry.io", "wixpress.com", "shopify.com", "example.com", "klaviyo.com")
IGNORE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".css", ".js")

OUTPUT_CSV = "brands_enriched.csv"


def clean_emails(raw_emails: list[str]) -> list[str]:
    valid = []
    for e in raw_emails:
        e_low = e.lower().strip(".")
        if any(e_low.endswith(ext) for ext in IGNORE_EXTS):
            continue
        if any(dom in e_low for dom in IGNORE_DOMAINS):
            continue
        if e_low not in valid:
            valid.append(e_low)
    # Prioritize founder/hello/press/info over generic noreply
    priority = ("founder", "hello", "press", "pr@", "media", "info", "contact", "support")
    valid.sort(key=lambda x: next((i for i, p in enumerate(priority) if p in x), 99))
    return [e for e in valid if "noreply" not in e and "no-reply" not in e]


def fetch_soup(url: str, timeout: int = 10) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
            return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        pass
    return None


def scrape_brand_site(website: str) -> tuple[str, str]:
    """Returns (best_email, brand_blurb) from a brand's homepage + contact/about pages."""
    if not website.startswith("http"):
        website = "https://" + website

    soup = fetch_soup(website)
    if not soup:
        return "", ""

    # 1. Grab brand blurb from meta description or first meaningful paragraph
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    blurb = meta.get("content", "").strip() if meta and meta.get("content") else ""

    # 2. Scan homepage for emails
    found_emails = EMAIL_REGEX.findall(soup.get_text(" "))
    for a in soup.select("a[href^='mailto:']"):
        found_emails.append(a["href"].replace("mailto:", "").split("?")[0])

    # 3. Check /contact and /about links if email or blurb is still missing
    subpages = set()
    base_domain = urlparse(website).netloc
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(k in href for k in ("contact", "about", "story", "press")):
            full_url = urljoin(website, a["href"])
            if urlparse(full_url).netloc == base_domain:
                subpages.add(full_url)

    for page_url in list(subpages)[:3]:
        sub_soup = fetch_soup(page_url)
        if not sub_soup:
            continue
        found_emails.extend(EMAIL_REGEX.findall(sub_soup.get_text(" ")))
        for a in sub_soup.select("a[href^='mailto:']"):
            found_emails.append(a["href"].replace("mailto:", "").split("?")[0])
        if len(blurb) < 40 and "about" in page_url.lower():
            paragraphs = [p.get_text(" ", strip=True) for p in sub_soup.find_all("p")]
            long_p = next((p for p in paragraphs if len(p) > 60), "")
            if long_p:
                blurb = long_p[:300]
        time.sleep(0.5)

    cleaned = clean_emails(found_emails)
    return (cleaned[0] if cleaned else ""), blurb.replace("\n", " ").strip()[:300]


def get_seed_brands_from_spotwatch() -> list[dict]:
    """Pulls microbrands from Spot.Watch registry table."""
    soup = fetch_soup("https://spot.watch/microbrand-registry/")
    brands = []
    if not soup:
        return brands

    for row in soup.select("table tr")[1:]:
        cols = [c.get_text(" ", strip=True) for c in row.find_all("td")]
        if len(cols) >= 3 and cols[2] and cols[2] != "—":
            brands.append({"brand_name": cols[0], "country": cols[1], "website": cols[2]})
    return brands


def main() -> None:
    # Start with Indian independents (zero customs hassle = highest odds) + scraped microbrands
    seed_brands = [
        {"brand_name": "Bangalore Watch Company", "country": "India", "website": "bangalorewatchco.in"},
        {"brand_name": "Jaipur Watch Company", "country": "India", "website": "jaipurwatches.com"},
        {"brand_name": "Delhi Watch Company", "country": "India", "website": "delhiwatchcompany.com"},
        {"brand_name": "Ajwain Watches", "country": "India", "website": "ajwa.in"},
        {"brand_name": "Argos Watches", "country": "India", "website": "argoswatch.in"},
        {"brand_name": "Coromandel Watch Co", "country": "India", "website": "coromandelwatchco.com"},
    ]
    seed_brands.extend(get_seed_brands_from_spotwatch())

    # Deduplicate by website
    seen = set()
    unique_brands = []
    for b in seed_brands:
        key = b["website"].lower().replace("www.", "").strip("/")
        if key not in seen:
            seen.add(key)
            unique_brands.append(b)

    print(f"Found {len(unique_brands)} brands. Extracting emails & brand stories...")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["brand_name", "country", "website", "email", "brand_blurb"])
        writer.writeheader()

        for idx, b in enumerate(unique_brands, 1):
            email, blurb = scrape_brand_site(b["website"])
            if email:
                writer.writerow({
                    "brand_name": b["brand_name"],
                    "country": b["country"],
                    "website": b["website"],
                    "email": email,
                    "brand_blurb": blurb,
                })
                print(f"[{idx}/{len(unique_brands)}] OK   {b['brand_name']} -> {email}")
            else:
                print(f"[{idx}/{len(unique_brands)}] SKIP {b['brand_name']} (no public email found)")
            time.sleep(0.5)


if __name__ == "__main__":
    main()