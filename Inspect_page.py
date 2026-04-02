from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

URL = "https://github.com/collections/machine-learning"

options = Options()
options.add_argument("--window-size=1400,900")
UA = (
    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
options.add_argument(UA)

driver = webdriver.Chrome(
    service = Service(ChromeDriverManager().install()),
    options = options
)

try:
    driver.get(URL)
    print("Waiting for page to load")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME,"article"))
    )

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # ── Report what elements we found ────────────────────────────────────────
    print("\n=== Page structure report ===\n")

    articles = soup.find_all("article")
    print(f"<article> elements found: {len(articles)}")

    if articles:
        print("\n--- First <article> raw HTML (truncated to 800 chars) ---")
        print(str(articles[0])[:800])
        print("\n...")

# Dump a clean version of the full page to a file for inspection

    with open("page_dump.html","w", encoding="utf-8") as f:
        f.write(soup.prettify())
    print("\n✅ Full rendered HTML saved to: page_dump.html")
    print("   Open it in a browser or text editor to explore the structure.")

    # ── Quick selector tests ──────────────────────────────────────────────────
    print("\n=== Selector test results ===")

    tests = {
        "article": soup.find_all("article"),
        "h1 a": soup.select("article h1 a"),
        "h2 a": soup.select("h2 a"),
        "itemprop=programmingLanguage": soup.find_all(itemprop="programmingLanguage"),
        'a[href*="stargazers"]': soup.select('a[href*="stargazers"]'),
        'a[href*="forks"]': soup.select('a[href*="forks"]')
    }

    for selector,results in tests.items():
        count = len(results)
        sample = results[0].get_text(strip=True)[:50] if results else ""
    print(f"  {selector:<40} → {count} found  (first: '{sample}')")

finally:
    input("\nPress Enter to close the browser...")
    driver.quit()
