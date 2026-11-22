# Nefis Yemek Tarifleri Scraper

[nefisyemektarifleri.com](https://www.nefisyemektarifleri.com) üzerindeki tariflerin **isimlerini** ve **malzemelerini** Selenium ile çekip `tarifler.json` dosyasında toplayan bot.

## Kurulum

```bash
pip install -r requirements.txt
```

Bilgisayarda Google Chrome kurulu olmalı. Uygun ChromeDriver'ı Selenium Manager otomatik indirir.

## Kullanım

```bash
python scraper.py                                   # varsayılan kategoriler, kategori başına 1 sayfa
python scraper.py --pages 3 --limit 200             # kategori başına 3 sayfa, en fazla 200 tarif
python scraper.py --categories corba-tarifleri tatli-tarifleri --no-headless
```

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `--categories` | Kategori slug'ları | çorba, et, sebze, tatlı, hamur işi, salata |
| `--pages` | Kategori başına sayfa sayısı | 1 |
| `--limit` | Toplam tarif sınırı (0 = sınırsız) | 0 |
| `--delay` | İstekler arası bekleme (sn) | 1.0 |
| `--output` | Çıktı dosyası | `tarifler.json` |
| `--no-headless` | Tarayıcıyı görünür aç | kapalı |

## Çıktı formatı

```json
{
  "kaynak": "https://www.nefisyemektarifleri.com",
  "olusturulma_tarihi": "...",
  "tarif_sayisi": 1,
  "tarifler": [
    {
      "isim": "Orman Kebabı",
      "malzemeler": ["3 adet patates", "2 adet patlıcan", "..."],
      "url": "https://www.nefisyemektarifleri.com/orman-kebabi-12666835/",
      "kategori": "et-yemekleri"
    }
  ]
}
```

> Not: Bu proje eğitim amaçlıdır. Siteye yük bindirmemek için istekler arasında bekleme yapılır; tarif içeriklerinin hakları sahiplerine aittir.
