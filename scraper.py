"""
Nefis Yemek Tarifleri Selenium botu.

Kategori sayfalarındaki tarif linklerini toplar, her tarif sayfasına girip
tarifin adını ve malzemelerini çeker, sonuçları JSON dosyasına yazar.

Kullanım:
    python scraper.py                          # varsayılan kategoriler, kategori başına 1 sayfa
    python scraper.py --pages 3 --limit 100    # kategori başına 3 sayfa, toplam en fazla 100 tarif
    python scraper.py --categories corba-tarifleri tatli-tarifleri --no-headless
"""

import argparse
import json
import time
from datetime import datetime, timezone

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://www.nefisyemektarifleri.com"
CATEGORY_URL = BASE_URL + "/kategori/tarifler/{slug}/"

DEFAULT_CATEGORIES = [
    "corba-tarifleri",
    "et-yemekleri",
    "sebze-yemekleri",
    "tatli-tarifleri",
    "hamurisi-tarifleri",
    "salata-meze-kanepe",
]

# Sayfa seçicileri
CARD_LINK_SELECTOR = ".recipe-cards .recipe-info a.title"
RECIPE_NAME_SELECTOR = "h1.recipe-name"
INGREDIENT_SELECTOR = "ul.recipe-materials li"


def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=tr-TR")
    # Görselleri yüklemeyerek sayfaları hızlandır
    options.add_experimental_option(
        "prefs", {"profile.managed_default_content_settings.images": 2}
    )
    # Reklam/izleme scriptleri tam yüklenmeden DOM hazır olunca devam et
    options.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=options)  # Selenium Manager chromedriver'ı otomatik indirir
    driver.set_page_load_timeout(30)
    return driver


def open_page(driver, url: str, wait_selector: str, timeout: int = 15) -> bool:
    try:
        driver.get(url)
    except TimeoutException:
        pass  # Sayfa tamamen yüklenmese de DOM genelde hazırdır
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
        )
        return True
    except TimeoutException:
        return False


def collect_recipe_links(driver, category: str, pages: int) -> list:
    links = []
    for page in range(1, pages + 1):
        url = CATEGORY_URL.format(slug=category)
        if page > 1:
            url += f"page/{page}/"
        print(f"[kategori] {category} - sayfa {page}: {url}")
        if not open_page(driver, url, CARD_LINK_SELECTOR):
            print("  ! tarif kartı bulunamadı, atlanıyor")
            continue
        for a in driver.find_elements(By.CSS_SELECTOR, CARD_LINK_SELECTOR):
            href = a.get_attribute("href")
            # Video ve blog sayfalarını atla, sadece tarif sayfalarını al
            if href and href.startswith(BASE_URL) and "/video/" not in href and href not in links:
                links.append(href)
    return links


def scrape_recipe(driver, url: str):
    if not open_page(driver, url, RECIPE_NAME_SELECTOR):
        return None
    name = driver.find_element(By.CSS_SELECTOR, RECIPE_NAME_SELECTOR).text.strip()
    ingredients = [
        li.get_attribute("textContent").strip()
        for li in driver.find_elements(By.CSS_SELECTOR, INGREDIENT_SELECTOR)
    ]
    ingredients = [i for i in ingredients if i]
    if not name or not ingredients:
        return None
    return {"isim": name, "malzemeler": ingredients, "url": url}


def main():
    parser = argparse.ArgumentParser(description="Nefis Yemek Tarifleri Selenium botu")
    parser.add_argument("--categories", nargs="+", default=DEFAULT_CATEGORIES,
                        help="Kategori slug'ları (ör. corba-tarifleri tatli-tarifleri)")
    parser.add_argument("--pages", type=int, default=1, help="Kategori başına taranacak sayfa sayısı")
    parser.add_argument("--limit", type=int, default=0, help="Toplam tarif sınırı (0 = sınırsız)")
    parser.add_argument("--delay", type=float, default=1.0, help="İstekler arası bekleme (saniye)")
    parser.add_argument("--output", default="tarifler.json", help="Çıktı JSON dosyası")
    parser.add_argument("--no-headless", action="store_true", help="Tarayıcıyı görünür aç")
    args = parser.parse_args()

    driver = create_driver(headless=not args.no_headless)
    recipes = []
    seen = set()
    try:
        for category in args.categories:
            links = collect_recipe_links(driver, category, args.pages)
            print(f"  {len(links)} tarif linki bulundu")
            for url in links:
                if args.limit and len(recipes) >= args.limit:
                    break
                if url in seen:
                    continue
                seen.add(url)
                time.sleep(args.delay)
                try:
                    recipe = scrape_recipe(driver, url)
                except WebDriverException as e:
                    print(f"  ! hata: {url} ({e.__class__.__name__})")
                    continue
                if recipe:
                    recipe["kategori"] = category
                    recipes.append(recipe)
                    print(f"  [{len(recipes)}] {recipe['isim']} ({len(recipe['malzemeler'])} malzeme)")
            if args.limit and len(recipes) >= args.limit:
                break
    finally:
        driver.quit()

    data = {
        "kaynak": BASE_URL,
        "olusturulma_tarihi": datetime.now(timezone.utc).isoformat(),
        "tarif_sayisi": len(recipes),
        "tarifler": recipes,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n{len(recipes)} tarif '{args.output}' dosyasına kaydedildi.")


if __name__ == "__main__":
    main()
