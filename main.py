"""
=============================================================
  GitHub ML Collections Scraper
  Target: https://github.com/collections/machine-learning
  Python 3.9+ | Selenium 4.x | webdriver-manager 4.x
=============================================================

WHAT THIS SCRAPES:
  For each repository card on the page:
    - Repository name (e.g. "tensorflow/tensorflow")
    - Owner username
    - Description
    - Primary language
    - Star count
    - Fork count
    - URL

OUTPUT:
  ml_repos.csv  — one row per repository
  ml_repos.json — same data as structured JSON

WHY SELENIUM (not just requests)?
  GitHub's collections page renders repository cards using
  JavaScript after the initial HTML loads. A plain
  requests.get() would give you an almost-empty shell.
  Selenium launches real Chrome, waits for JS to finish,
  then lets us parse the fully-rendered DOM.

HOW TO RUN:
  1. pip install selenium webdriver-manager beautifulsoup4
  2. python github_ml_scraper.py
=============================================================
"""

import csv
import json
import time
import re

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup


# ── Configuration ────────────────────────────────────────────────────────────

TARGET_URL = "https://github.com/collections/machine-learning"

# Set to False while debugging — lets you watch the browser
HEADLESS = False

# Seconds to wait for page elements before timing out
WAIT_TIMEOUT = 15

# Output file paths
CSV_OUTPUT  = "ml_repos.csv"
JSON_OUTPUT = "ml_repos.json"


# ── Browser setup ─────────────────────────────────────────────────────────────

def create_driver() -> webdriver.Chrome:
    """
    Create and return a configured Chrome WebDriver.

    Key options explained:
      --headless=new        Run Chrome invisibly (no window pops up).
                            Remove this line while debugging so you can
                            watch what the browser actually sees.

      --no-sandbox          Required in some Linux/Docker environments.

      --disable-dev-shm-usage
                            Prevents crashes in environments with limited
                            shared memory (Docker, CI, etc).

      --window-size=...     Ensures the page renders at a proper desktop
                            width — GitHub's layout differs on narrow screens.

      user-agent            GitHub checks the User-Agent header. Using a
                            real browser string helps avoid bot detection.
    """
    options = Options()

    if HEADLESS:
        options.add_argument("--headless=new")      # Modern headless flag (Chrome 112+)

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")  # Reduce bot signals
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    # Identify ourselves with a real browser User-Agent
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    # webdriver-manager automatically downloads the correct ChromeDriver
    # version for your installed Chrome — no manual download needed
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    return driver


# ── Parsing helpers ───────────────────────────────────────────────────────────

def parse_star_count(raw: str) -> int:
    """
    Convert GitHub's abbreviated star counts to integers.
    Examples:
        "42.1k" → 42100
        "1.2m"  → 1200000
        "893"   → 893
        ""      → 0
    """
    raw = raw.strip().lower().replace(",", "")
    if not raw:
        return 0
    try:
        if raw.endswith("k"):
            return int(float(raw[:-1]) * 1_000)
        elif raw.endswith("m"):
            return int(float(raw[:-1]) * 1_000_000)
        else:
            return int(raw)
    except ValueError:
        return 0


def parse_repo_card(card_soup) -> dict:
    """
    Extract all data fields from a single repository card element.

    GitHub's collections page uses this HTML structure for each card:

      <article class="border ...">
        <h1>
          <a href="/tensorflow/tensorflow">tensorflow/tensorflow</a>
        </h1>
        <p>An Open Source Machine Learning Framework ...</p>
        <div>
          <span itemprop="programmingLanguage">Python</span>
          <a href="...stargazers">193k</a>
          <a href="...forks">...</a>
        </div>
      </article>

    We use BeautifulSoup selectors to pull each piece out.
    If a field is missing (some repos have no description, no language),
    we return a safe default rather than crashing.
    """
    repo = {
        "name":        "",
        "owner":       "",
        "description": "",
        "language":    "",
        "stars":       0,
        "forks":       0,
        "url":         "",
    }

    # ── Name & URL ──────────────────────────────────────
    # The repo link is the first <a> inside the <h1> or <h2>
    name_tag = card_soup.find("h1") or card_soup.find("h2")
    if name_tag:
        link = name_tag.find("a", href=True)
        if link:
            href = link.get("href", "")           # e.g. "/tensorflow/tensorflow"
            repo["url"] = "https://github.com" + href
            parts = href.strip("/").split("/")
            if len(parts) == 2:
                repo["owner"] = parts[0]
                repo["name"]  = parts[1]
            else:
                repo["name"] = link.get_text(strip=True)

    # ── Description ─────────────────────────────────────
    # GitHub puts the repo description in a <p> inside the card
    desc_tag = card_soup.find("p")
    if desc_tag:
        repo["description"] = desc_tag.get_text(strip=True)

    # ── Language ────────────────────────────────────────
    # The language tag uses itemprop="programmingLanguage"
    lang_tag = card_soup.find(itemprop="programmingLanguage")
    if lang_tag:
        repo["language"] = lang_tag.get_text(strip=True)

    # ── Stars ───────────────────────────────────────────
    # Star count links contain "/stargazers" in their href
    star_link = card_soup.find("a", href=re.compile(r"/stargazers"))
    if star_link:
        repo["stars"] = parse_star_count(star_link.get_text(strip=True))

    # ── Forks ───────────────────────────────────────────
    # Fork count links contain "/forks" in their href
    fork_link = card_soup.find("a", href=re.compile(r"/forks"))
    if fork_link:
        repo["forks"] = parse_star_count(fork_link.get_text(strip=True))

    return repo


# ── Main scraping logic ───────────────────────────────────────────────────────

def scrape_ml_collection() -> list[dict]:
    """
    Open GitHub's ML collection page, wait for it to fully load,
    then parse every repository card on the page.

    Returns a list of repo dictionaries.
    """
    driver = create_driver()
    repos  = []

    try:
        print(f"Opening: {TARGET_URL}")
        driver.get(TARGET_URL)

        # ── Wait for the page to load ────────────────────────────────────────
        # We wait until at least one <article> element appears in the DOM.
        # This confirms that JavaScript has finished rendering the repo cards.
        # WebDriverWait is smarter than time.sleep() — it stops as soon as
        # the condition is met, rather than always waiting the full duration.
        wait = WebDriverWait(driver, WAIT_TIMEOUT)

        try:
            wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "article"))
            )
            print("Page loaded — repo cards found.")
        except TimeoutException:
            print("WARNING: Timed out waiting for article elements.")
            print("The page may use different HTML structure — check manually.")
            # We'll still try to parse whatever loaded

        # ── Optional: scroll to load any lazy content ───────────────────────
        # GitHub sometimes lazy-loads content below the fold.
        # Scrolling to the bottom triggers those loads.
        print("Scrolling to trigger any lazy-loaded content...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)   # Brief pause to let lazy content load
        driver.execute_script("window.scrollTo(0, 0);")

        # ── Hand off the rendered HTML to BeautifulSoup ──────────────────────
        # driver.page_source gives us the fully-rendered HTML (after JS ran),
        # not the raw initial HTML. This is the key advantage of Selenium.
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # ── Find all repository cards ────────────────────────────────────────
        # GitHub collections wrap each repo in an <article> element.
        # This is more reliable than CSS classes (which GitHub changes often).
        cards = soup.find_all("article")
        print(f"Found {len(cards)} repository cards.")

        if not cards:
            # Fallback: try finding repo items via a common class pattern
            # GitHub sometimes uses <li> or <div> with repo-related classes
            cards = soup.find_all("li", class_=re.compile(r"col-"))
            print(f"Fallback: found {len(cards)} items via col- class pattern.")

        # ── Parse each card ──────────────────────────────────────────────────
        for i, card in enumerate(cards, 1):
            repo = parse_repo_card(card)

            # Skip cards that didn't yield a name (probably nav/sidebar items)
            if not repo["name"]:
                continue

            repos.append(repo)
            print(f"  [{i}] {repo['owner']}/{repo['name']} "
                  f"(★ {repo['stars']:,} | {repo['language']})")

    finally:
        # ALWAYS quit the driver — even if an exception was raised.
        # Without this, orphan Chrome processes pile up in the background.
        print("\nClosing browser...")
        driver.quit()

    return repos


# ── Output functions ──────────────────────────────────────────────────────────

def save_csv(repos: list[dict], path: str) -> None:
    """Save the list of repo dicts to a CSV file."""
    if not repos:
        print("No data to save.")
        return

    fieldnames = ["name", "owner", "description", "language", "stars", "forks", "url"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(repos)

    print(f"Saved CSV  → {path}")


def save_json(repos: list[dict], path: str) -> None:
    """Save the list of repo dicts to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(repos, f, indent=2, ensure_ascii=False)

    print(f"Saved JSON → {path}")


def print_summary(repos: list[dict]) -> None:
    """Print a quick summary table to the terminal."""
    if not repos:
        print("No repositories scraped.")
        return

    print("\n" + "═" * 65)
    print(f"  SCRAPED {len(repos)} REPOSITORIES FROM GITHUB ML COLLECTION")
    print("═" * 65)

    # Sort by stars descending for a nice display
    sorted_repos = sorted(repos, key=lambda r: r["stars"], reverse=True)

    print(f"  {'Repository':<35} {'Stars':>8}  {'Language'}")
    print("  " + "─" * 60)

    for r in sorted_repos[:15]:  # Show top 15
        full_name = f"{r['owner']}/{r['name']}" if r['owner'] else r['name']
        lang = r['language'] or "—"
        print(f"  {full_name:<35} {r['stars']:>8,}  {lang}")

    if len(repos) > 15:
        print(f"  ... and {len(repos) - 15} more (see CSV/JSON output)")

    print("═" * 65 + "\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🤖 GitHub ML Collection Scraper")
    print("   Target:", TARGET_URL)
    print("   Headless mode:", HEADLESS)
    print()

    repos = scrape_ml_collection()

    if repos:
        save_csv(repos, CSV_OUTPUT)
        save_json(repos, JSON_OUTPUT)
        print_summary(repos)
    else:
        print("\n⚠️  No repositories were scraped.")
        print("   Possible reasons:")
        print("   1. GitHub changed its HTML structure — inspect the page and")
        print("      update the selectors in parse_repo_card()")
        print("   2. You're being rate-limited — try adding a longer sleep")
        print("      after driver.get() or run with HEADLESS = False to debug")
        print("   3. The page requires JavaScript that didn't finish loading —")
        print("      increase WAIT_TIMEOUT")