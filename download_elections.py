"""
download_elections.py
─────────────────────
Scrapes, downloads and extracts all Italian election zip files into:

    data/
    ├── Camera/
    │   ├── 19480418/   ← files extracted here
    │   ├── 19530607/
    │   └── ...
    └── Comunali/
        ├── 19700607/
        └── ...

    data/links/
        camera_links.txt    ← cached after first scrape
        comunali_links.txt

HOW TO RUN:
    conda activate DataMining25_regipy
    python3 download_elections.py

To test on a few files first, set TEST_MODE = True below.
Once happy, set it back to False and re-run — already extracted
folders are skipped automatically.
"""

# ── 0. Install dependencies if missing ───────────────────────────────────────
import subprocess, sys
for pkg in ["selenium", "webdriver-manager", "beautifulsoup4", "requests", "lxml", "tqdm"]:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pkg])

# ── 1. Imports ────────────────────────────────────────────────────────────────
import time
import zipfile
import requests
from pathlib import Path
from tqdm import tqdm
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager

# ── 2. Configuration ──────────────────────────────────────────────────────────
BASE_URL     = "https://elezionistorico.interno.gov.it"
PAGE_URL     = BASE_URL + "/eligendo/opendata.php"
DATA_ROOT    = Path("data")
CAMERA_DIR   = DATA_ROOT / "Camera"
COMUNALI_DIR = DATA_ROOT / "Comunali"
LINKS_DIR    = DATA_ROOT / "links"
CAMERA_CACHE   = LINKS_DIR / "camera_links.txt"
COMUNALI_CACHE = LINKS_DIR / "comunali_links.txt"

DELAY_BETWEEN_DOWNLOADS = 2   # seconds between each download (be polite)

# Set to True to test on a small subset first before the full run
TEST_MODE        = False
TEST_CAMERA_N    = 3    # how many Camera files to test with
TEST_COMUNALI_N  = 5    # how many Comunali files to test with

# ── 3. Folder setup ───────────────────────────────────────────────────────────
for folder in [CAMERA_DIR, COMUNALI_DIR, LINKS_DIR]:
    folder.mkdir(parents=True, exist_ok=True)
print("📁 Folders ready.\n")

# ── 4. Selenium helpers ───────────────────────────────────────────────────────
def build_driver(headless: bool = True) -> webdriver.Chrome:
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    service = ChromeService(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


def select_year(driver, wait, select_name: str, year: str = None, last: bool = False):
    """Select a year from a <select> dropdown by visible text, or the last option."""
    el = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, f"select[name='{select_name}']"))
    )
    sel = Select(el)
    available = [o.text.strip() for o in sel.options if o.text.strip()]
    if last:
        target = available[0]   # dropdowns are newest-first, so first = latest year
    elif year in available:
        target = year
    else:
        target = available[0]
        print(f"  ⚠️  '{year}' not found in {select_name}, falling back to '{target}'")
    sel.select_by_visible_text(target)
    print(f"  [{select_name}] → {target}")


def collect_zip_links_camera(driver) -> list:
    """Paginate through Camera results. Next button always has data-dt-idx=3."""
    all_links, page = [], 1
    while True:
        soup = BeautifulSoup(driver.page_source, "lxml")
        links = [a["href"] for a in soup.find_all("a", href=True)
                 if a["href"].lower().endswith(".zip")]
        all_links.extend(links)
        print(f"  Page {page}: {len(links)} link(s)  (total: {len(all_links)})")
        btn = driver.find_elements(By.CSS_SELECTOR,
                                   "a.paginate_button.next[data-dt-idx='3']")
        if not btn or "disabled" in btn[0].get_attribute("class"):
            print("  No more pages — done.")
            break
        driver.execute_script("arguments[0].click();", btn[0])
        time.sleep(1.5)
        page += 1
    return all_links


def collect_zip_links_comunali(driver) -> list:
    """
    Paginate through Comunali results.
    data-dt-idx on the next button shifts as the page window moves:
      pages 1–4  → idx 7
      pages 5–13 → idx 6
      pages 14+  → idx 7
    """
    all_links, page = [], 1
    while True:
        soup = BeautifulSoup(driver.page_source, "lxml")
        links = [a["href"] for a in soup.find_all("a", href=True)
                 if a["href"].lower().endswith(".zip")]
        all_links.extend(links)
        print(f"  Page {page}: {len(links)} link(s)  (total: {len(all_links)})")
        idx = 6 if 5 <= page <= 13 else 7
        btn = driver.find_elements(By.CSS_SELECTOR,
                                   f"a.paginate_button.next[data-dt-idx='{idx}']")
        if not btn or "disabled" in btn[0].get_attribute("class"):
            print("  No more pages — done.")
            break
        driver.execute_script("arguments[0].click();", btn[0])
        time.sleep(1.5)
        page += 1
    return all_links

# ── 5. Scrape functions (with caching) ───────────────────────────────────────
def scrape_camera_links() -> list:
    if CAMERA_CACHE.exists():
        print("📋 Camera links loaded from cache.")
        return [l for l in CAMERA_CACHE.read_text().splitlines() if l.strip()]

    print("🌐 Scraping Camera links...")
    driver = build_driver()
    wait   = WebDriverWait(driver, 20)
    try:
        driver.get(PAGE_URL)
        radio = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input#camera[type='radio']")))
        driver.execute_script("arguments[0].click();", radio)
        time.sleep(1.5)
        select_year(driver, wait, "sel_anno_da", "1948")
        time.sleep(1)
        select_year(driver, wait, "sel_anno_a", "2022")
        time.sleep(2)
        links = collect_zip_links_camera(driver)
    finally:
        driver.quit()

    CAMERA_CACHE.write_text("\n".join(links))
    print(f"  ✔ {len(links)} links cached → {CAMERA_CACHE}\n")
    return links


def scrape_comunali_links() -> list:
    if COMUNALI_CACHE.exists():
        print("📋 Comunali links loaded from cache.")
        return [l for l in COMUNALI_CACHE.read_text().splitlines() if l.strip()]

    print("🌐 Scraping Comunali links...")
    driver = build_driver()
    wait   = WebDriverWait(driver, 20)
    try:
        driver.get(PAGE_URL)
        radio = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "input#comunali[type='radio']")))
        driver.execute_script("arguments[0].click();", radio)
        time.sleep(1.5)
        select_year(driver, wait, "sel_anno_da", "1970")
        time.sleep(1)
        select_year(driver, wait, "sel_anno_a", "2025")
        time.sleep(2)
        links = collect_zip_links_comunali(driver)
    finally:
        driver.quit()

    COMUNALI_CACHE.write_text("\n".join(links))
    print(f"  ✔ {len(links)} links cached → {COMUNALI_CACHE}\n")
    return links

# ── 6. Download + extract ─────────────────────────────────────────────────────
def download_and_extract(relative_url: str, dest_parent: Path):
    """
    Download one zip and extract it into dest_parent/<date>/.

    e.g. /daithome/documenti/opendata/camera/camera-19830626.zip
         → data/Camera/19830626/<extracted files>
    """
    full_url  = BASE_URL + relative_url
    filename  = relative_url.split("/")[-1]             # camera-19830626.zip
    date_part = filename.replace(".zip", "").split("-", 1)[-1]  # 19830626
    dest_dir  = dest_parent / date_part

    # Skip if already extracted and non-empty
    if dest_dir.exists() and any(dest_dir.iterdir()):
        print(f"  ⏭  {filename} already extracted — skipping")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / filename

    # Stream download with progress bar
    try:
        with requests.get(full_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with open(zip_path, "wb") as f, tqdm(
                desc=f"  ⬇  {filename}",
                total=total,
                unit="B", unit_scale=True, unit_divisor=1024,
                leave=True,
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    bar.update(len(chunk))
    except Exception as e:
        print(f"  ❌ Failed to download {filename}: {e}")
        if zip_path.exists():
            zip_path.unlink()   # clean up partial download
        return

    # Extract
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest_dir)
        zip_path.unlink()       # delete zip after successful extraction
        print(f"  ✔  Extracted → {dest_dir}/")
    except zipfile.BadZipFile:
        print(f"  ❌ Bad zip file: {filename} — leaving for inspection")

# ── 7. Main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    camera_links   = scrape_camera_links()
    comunali_links = scrape_comunali_links()

    # Apply test slice if TEST_MODE is on
    if TEST_MODE:
        print(f"⚠️  TEST MODE — Camera: first {TEST_CAMERA_N}, Comunali: first {TEST_COMUNALI_N}\n")
        camera_links   = camera_links[:TEST_CAMERA_N]
        comunali_links = comunali_links[:TEST_COMUNALI_N]

    total = len(camera_links) + len(comunali_links)
    print(f"\n{'='*55}")
    print(f"  📷 Camera   → {len(camera_links):>3} file(s) to process")
    print(f"  🏛 Comunali → {len(comunali_links):>3} file(s) to process")
    print(f"  {'─'*37}")
    print(f"     TOTAL    → {total:>3}")
    print(f"{'='*55}\n")

    print("📷 Downloading Camera files...\n")
    for link in camera_links:
        download_and_extract(link, CAMERA_DIR)
        time.sleep(DELAY_BETWEEN_DOWNLOADS)

    print("\n🏛 Downloading Comunali files...\n")
    for link in comunali_links:
        download_and_extract(link, COMUNALI_DIR)
        time.sleep(DELAY_BETWEEN_DOWNLOADS)

    print("\n✅ All done!")
