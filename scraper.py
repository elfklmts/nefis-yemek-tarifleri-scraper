"""
Nefis Yemek Tarifleri Selenium botu.

Her kategorinin toplam sayfa sayısını otomatik bulur, tüm sayfalardaki tarif
linklerini toplar, her tarif sayfasına girip tarifin adını ve malzemelerini çeker.

- Sonuçlar tarif tarif `veri/<kategori>.jsonl` dosyalarına eklenir; bot durdurulsa
  bile tekrar çalıştırıldığında kaldığı sayfadan devam eder.
- `--export` ile JSONL verisi GitHub'ın 100 MB dosya sınırına takılmayacak şekilde
  `tarifler/<kategori>-001.json, -002.json ...` parçalarına dönüştürülür.

Kullanım:
    python scraper.py                                # tüm kategoriler, tüm sayfalar
    python scraper.py --workers 3                    # 3 paralel tarayıcı
    python scraper.py --categories corba-tarifleri --max-pages 5
    python scraper.py --export                       # JSONL -> JSON parçaları
"""

import argparse
import glob
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://www.nefisyemektarifleri.com"
CATEGORY_URL = BASE_URL + "/kategori/tarifler/{slug}/"

# Küçükten büyüğe sıralı: tarama yarıda kalırsa bile mümkün olduğunca çok kategori tamamlanır
DEFAULT_CATEGORIES = [
    "corba-tarifleri",      # ~1.741 sayfa
    "salata-meze-kanepe",   # ~2.370 sayfa
    "sebze-yemekleri",      # ~2.564 sayfa
    "et-yemekleri",         # ~4.402 sayfa
    "hamurisi-tarifleri",   # ~6.552 sayfa
    "tatli-tarifleri",      # ~12.187 sayfa
]

CARD_LINK_SELECTOR = ".recipe-cards .recipe-info a.title"
RECIPE_NAME_SELECTOR = "h1.recipe-name"
INGREDIENT_SELECTOR = "ul.recipe-materials li"

# Hızlı mod: tarayıcı sitede açıkken sayfaları çizdirmeden, tarayıcının kendi fetch()'i
# ile indirip DOMParser ile ayrıştırır. Reklam/görsel/script yüklenmediği için
# tam sayfa açmaya göre ~20 kat hızlıdır.
LIST_JS = r"""
const [url, done] = [arguments[0], arguments[arguments.length - 1]];
fetch(url).then(r => r.ok ? r.text() : Promise.reject(r.status)).then(h => {
  const d = new DOMParser().parseFromString(h, 'text/html');
  done([...new Set([...d.querySelectorAll(arguments[1])].map(a => a.href))]);
}).catch(e => done({hata: String(e)}));
"""

RECIPES_JS = r"""
const [urls, conc, nameSel, ingSel, done] = arguments;
const parse = (html) => {
  const d = new DOMParser().parseFromString(html, 'text/html');
  const h = d.querySelector(nameSel);
  if (!h) return null;
  const ing = [...d.querySelectorAll(ingSel)].map(li => li.textContent.trim()).filter(Boolean);
  return {isim: h.textContent.trim(), malzemeler: ing};
};
const out = new Array(urls.length); let i = 0;
async function worker() {
  while (i < urls.length) {
    const k = i++;
    try {
      const r = await fetch(urls[k]);
      out[k] = r.ok ? parse(await r.text()) : {hata: r.status};
    } catch (e) { out[k] = {hata: String(e)}; }
  }
}
Promise.all(Array.from({length: conc}, worker)).then(() => done(out));
"""

DATA_DIR = "veri"          # ham veri (JSONL) + ilerleme
EXPORT_DIR = "tarifler"    # pushlanacak JSON parçaları
CHUNK_SIZE = 20000         # bir JSON parçasındaki tarif sayısı (~10 MB)
RESTART_EVERY = 300        # bellek sızıntısına karşı tarayıcıyı her N sayfada yeniden başlat


# --------------------------------------------------------------------------- tarayıcı

def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=tr-TR")
    options.add_experimental_option(
        "prefs", {"profile.managed_default_content_settings.images": 2}
    )
    options.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=options)  # Selenium Manager uygun chromedriver'ı indirir
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(180)
    return driver


class Worker:
    """Her iş parçacığına ait, belirli aralıklarla yenilenen tarayıcı."""

    def __init__(self, headless: bool):
        self.headless = headless
        self.driver = None
        self.pages_done = 0

    def get(self):
        if self.driver is None or self.pages_done >= RESTART_EVERY:
            self.close()
            self.driver = create_driver(self.headless)
            self.pages_done = 0
            try:
                self.driver.get(BASE_URL + "/iletisim/")  # hafif bir site sayfası
            except TimeoutException:
                pass
        return self.driver

    def reset(self):
        self.close()

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


_local = threading.local()
_all_workers = []
_workers_lock = threading.Lock()


def current_worker(headless: bool) -> Worker:
    if not hasattr(_local, "worker"):
        _local.worker = Worker(headless)
        with _workers_lock:
            _all_workers.append(_local.worker)
    return _local.worker


def open_page(driver, url: str, wait_selector: str, timeout: int = 15) -> bool:
    try:
        driver.get(url)
    except TimeoutException:
        pass
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
        )
        return True
    except TimeoutException:
        return False


# --------------------------------------------------------------------------- kazıma

def category_page_url(category: str, page: int) -> str:
    url = CATEGORY_URL.format(slug=category)
    return url if page == 1 else f"{url}page/{page}/"


def detect_page_count(driver, category: str) -> int:
    """Kategorinin ilk sayfasındaki sayfalama linklerinden son sayfa numarasını bulur."""
    if not open_page(driver, category_page_url(category, 1), CARD_LINK_SELECTOR):
        return 0
    pattern = re.compile(re.escape(f"/kategori/tarifler/{category}/page/") + r"(\d+)")
    pages = [1]
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/page/']"):
        m = pattern.search(a.get_attribute("href") or "")
        if m:
            pages.append(int(m.group(1)))
    return max(pages)


def scrape_category_page(category: str, page: int, seen: set, seen_lock, args, headless: bool):
    """Bir kategori sayfasındaki tüm tarifleri çeker. Başarılıysa tarif listesi döner."""
    worker = current_worker(headless)
    for attempt in range(3):
        try:
            driver = worker.get()
            links = driver.execute_async_script(LIST_JS, category_page_url(category, page), CARD_LINK_SELECTOR)
            if isinstance(links, dict):  # fetch hatası
                raise WebDriverException(f"liste alınamadı: {links.get('hata')}")
            links = [l for l in links if l.startswith(BASE_URL) and "/video/" not in l]
            with seen_lock:
                links = [l for l in links if l not in seen]
                seen.update(links)

            results = driver.execute_async_script(
                RECIPES_JS, links, args.concurrency, RECIPE_NAME_SELECTOR, INGREDIENT_SELECTOR)
            recipes, failed = [], 0
            for url, r in zip(links, results):
                if r and "isim" in r and r["malzemeler"]:
                    recipes.append({"isim": r["isim"], "malzemeler": r["malzemeler"],
                                    "url": url, "kategori": category})
                elif r and "hata" in r:
                    failed += 1
            if links and failed > len(links) // 2:  # site yavaşlattı/engelledi: bekle, tekrar dene
                with seen_lock:
                    seen.difference_update(links)
                raise WebDriverException(f"{failed}/{len(links)} tarif alınamadı")
            worker.pages_done += 1
            time.sleep(args.delay)
            return recipes
        except Exception as e:  # tarayıcı çökmesi vb. her hatada tarayıcıyı yenile
            print(f"  ! {category} s.{page} hata ({str(e).strip()[:80]}), tekrar deneniyor")
            worker.reset()
            time.sleep(10 * (attempt + 1))
    return None  # başarısız: ilerlemeye yazılmaz, sonraki çalıştırmada tekrar denenir


# --------------------------------------------------------------------------- ilerleme

def progress_path():
    return os.path.join(DATA_DIR, "ilerleme.json")


def load_progress():
    try:
        with open(progress_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_progress(progress):
    tmp = progress_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=1)
    os.replace(tmp, progress_path())


def load_seen_urls():
    seen = set()
    for path in glob.glob(os.path.join(DATA_DIR, "*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["url"])
                except (json.JSONDecodeError, KeyError):
                    pass
    return seen


# --------------------------------------------------------------------------- ana akış

def run(args):
    os.makedirs(DATA_DIR, exist_ok=True)
    progress = load_progress()
    seen = load_seen_urls()
    seen_lock = threading.Lock()
    headless = not args.no_headless
    print(f"Daha önce çekilmiş tarif: {len(seen)}")

    try:
        for category in args.categories:
            state = progress.setdefault(category, {"toplam_sayfa": 0, "tamamlanan": []})
            if not state["toplam_sayfa"]:
                state["toplam_sayfa"] = detect_page_count(current_worker(headless).get(), category)
                save_progress(progress)
            total = state["toplam_sayfa"]
            if args.max_pages:
                total = min(total, args.max_pages)
            out_path = os.path.join(DATA_DIR, f"{category}.jsonl")
            for attempt in range(1, 4):  # başarısız sayfalar için en fazla 3 tur
                done = set(state["tamamlanan"])
                todo = [p for p in range(1, total + 1) if p not in done]
                print(f"\n[{category}] {state['toplam_sayfa']} sayfa, {len(done)} tamamlanmış, "
                      f"{len(todo)} kaldı (tur {attempt})")
                if not todo:
                    break
                if attempt > 1:
                    time.sleep(60)  # siteye nefes aldır
                started = time.time()
                with open(out_path, "a", encoding="utf-8") as out, \
                        ThreadPoolExecutor(max_workers=args.workers) as pool:
                    futures = {
                        pool.submit(scrape_category_page, category, p, seen, seen_lock, args, headless): p
                        for p in todo
                    }
                    for i, fut in enumerate(as_completed(futures), 1):
                        page = futures[fut]
                        recipes = fut.result()
                        if recipes is None:
                            print(f"  ! sayfa {page} başarısız, sonra tekrar denenecek")
                            continue
                        for r in recipes:
                            out.write(json.dumps(r, ensure_ascii=False) + "\n")
                        out.flush()
                        state["tamamlanan"].append(page)
                        save_progress(progress)
                        rate = (time.time() - started) / i
                        eta_h = rate * (len(todo) - i) / 3600
                        print(f"  sayfa {page} ✓ {len(recipes)} tarif | {i}/{len(todo)} | kalan ~{eta_h:.1f} saat")
    except KeyboardInterrupt:
        print("\nDurduruldu. Tekrar çalıştırınca kaldığı yerden devam eder.")
        return 130
    finally:
        for w in _all_workers:
            w.close()

    remaining = 0
    for category in args.categories:
        state = progress.get(category, {})
        total = state.get("toplam_sayfa", 0)
        if args.max_pages:
            total = min(total, args.max_pages)
        remaining += total - len(set(state.get("tamamlanan", [])))
    print(f"\nBitti. Kalan sayfa: {remaining}")
    return 0 if remaining == 0 and all(progress.get(c, {}).get("toplam_sayfa") for c in args.categories) else 2


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def is_useful(recipe: dict) -> str:
    """Tarif işe yarıyorsa boş string, yaramıyorsa eleme sebebini döner."""
    if len(recipe["isim"]) < 3:
        return "isimsiz"
    if not recipe["url"].startswith(BASE_URL + "/"):
        return "gecersiz_link"
    if len(recipe["malzemeler"]) < 2:
        return "az_malzeme"            # 0-1 malzemeli kayıtlar gerçek tarif değil
    if len(recipe["malzemeler"]) > 60:
        return "bozuk_malzeme_listesi"
    if any(len(m) > 250 for m in recipe["malzemeler"]):
        return "bozuk_malzeme_listesi"  # malzeme yerine paragraf yazılmış
    return ""


def export(args):
    """veri/*.jsonl -> tarifler/<kategori>-NNN.json (her biri en fazla CHUNK_SIZE tarif).

    Eleme: isimsiz / linksiz kayıtlar, 2'den az malzemesi olanlar, bozuk malzeme
    listeleri ve aynı isim + aynı malzemelerle tekrar eden tarifler çıkarılır.
    """
    os.makedirs(EXPORT_DIR, exist_ok=True)
    for old in glob.glob(os.path.join(EXPORT_DIR, "*.json")):
        os.remove(old)
    summary, removed = {}, {}
    seen_urls, seen_content = set(), set()
    for category in DEFAULT_CATEGORIES + sorted(
            {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(DATA_DIR, "*.jsonl"))}
            - set(DEFAULT_CATEGORIES)):
        path = os.path.join(DATA_DIR, f"{category}.jsonl")
        if not os.path.exists(path):
            continue
        recipes = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                r = {"isim": clean_text(r.get("isim")),
                     "malzemeler": [m for m in (clean_text(x) for x in r.get("malzemeler", [])) if m],
                     "url": r.get("url", ""),
                     "kategori": category}
                reason = is_useful(r)
                key = (r["isim"].lower(), tuple(sorted(m.lower() for m in r["malzemeler"])))
                if not reason and r["url"] in seen_urls:
                    reason = "tekrar"
                if not reason and key in seen_content:
                    reason = "tekrar"
                if reason:
                    removed[reason] = removed.get(reason, 0) + 1
                    continue
                seen_urls.add(r["url"])
                seen_content.add(key)
                recipes.append(r)
        parts = [recipes[i:i + CHUNK_SIZE] for i in range(0, len(recipes), CHUNK_SIZE)] or [[]]
        for n, part in enumerate(parts, 1):
            # Tarih yazılmaz: dolmuş parçalar değişmez, git geçmişi şişmez
            with open(os.path.join(EXPORT_DIR, f"{category}-{n:03d}.json"), "w", encoding="utf-8") as f:
                json.dump({"kaynak": BASE_URL, "kategori": category, "parca": n,
                           "tarif_sayisi": len(part), "tarifler": part},
                          f, ensure_ascii=False, indent=1)
        summary[category] = {"tarif_sayisi": len(recipes), "dosya_sayisi": len(parts)}
        print(f"{category}: {len(recipes)} tarif, {len(parts)} dosya")
    progress = load_progress()
    for category, state in progress.items():
        if category in summary:
            summary[category]["taranan_sayfa"] = len(set(state.get("tamamlanan", [])))
            summary[category]["toplam_sayfa"] = state.get("toplam_sayfa", 0)
    with open(os.path.join(EXPORT_DIR, "ozet.json"), "w", encoding="utf-8") as f:
        json.dump({"guncelleme_tarihi": datetime.now(timezone.utc).isoformat(),
                   "toplam_tarif": sum(s["tarif_sayisi"] for s in summary.values()),
                   "elenen_tarif": removed,
                   "kategoriler": summary}, f, ensure_ascii=False, indent=1)
    print(f"Elenen: {removed}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Nefis Yemek Tarifleri Selenium botu")
    parser.add_argument("--categories", nargs="+", default=DEFAULT_CATEGORIES,
                        help="Kategori slug'ları (ör. corba-tarifleri tatli-tarifleri)")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="Kategori başına en fazla sayfa (0 = tüm sayfalar, otomatik bulunur)")
    parser.add_argument("--workers", type=int, default=2, help="Paralel tarayıcı sayısı")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Her tarayıcıda aynı anda indirilen tarif sayısı")
    parser.add_argument("--delay", type=float, default=1.0, help="Her kategori sayfasından sonra bekleme (sn)")
    parser.add_argument("--no-headless", action="store_true", help="Tarayıcıyı görünür aç")
    parser.add_argument("--export", action="store_true", help="Toplanan veriyi JSON parçalarına dönüştür")
    args = parser.parse_args()

    sys.exit(export(args) if args.export else run(args))


if __name__ == "__main__":
    main()
