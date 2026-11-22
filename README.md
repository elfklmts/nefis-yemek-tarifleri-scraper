# Nefis Yemek Tarifleri Scraper

[nefisyemektarifleri.com](https://www.nefisyemektarifleri.com) üzerindeki tariflerin **isimlerini** ve **malzemelerini** Selenium ile çekip `tarifler.json` dosyasında toplayan bot.

## Kurulum

```bash
pip install -r requirements.txt
```

Bilgisayarda Google Chrome kurulu olmalı. Uygun ChromeDriver'ı Selenium Manager otomatik indirir.

## Kullanım

Tüm siteyi taramak için (çökmelere karşı kendini yeniden başlatır, her 2 saatte bir veriyi GitHub'a pushlar):

```bash
caffeinate -i ./calistir.sh
```

Elle çalıştırmak için:

```bash
python scraper.py                      # tüm kategoriler, tüm sayfalar (sayfa sayısı otomatik bulunur)
python scraper.py --categories corba-tarifleri --max-pages 5
python scraper.py --export             # toplanan veriyi tarifler/ klasörüne JSON parçaları olarak yaz
```

Bot her tarifi çektikçe `veri/<kategori>.jsonl` dosyasına ekler ve tamamlanan sayfaları
`veri/ilerleme.json`'a yazar. Durdurulursa (Ctrl+C) tekrar çalıştırıldığında kaldığı yerden devam eder.

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `--categories` | Kategori slug'ları | çorba, et, sebze, tatlı, hamur işi, salata |
| `--max-pages` | Kategori başına en fazla sayfa (0 = hepsi) | 0 |
| `--workers` | Paralel tarayıcı sayısı (hız sınırı hepsi için ortak) | 1 |
| `--min-gap` | İstekler arası en kısa bekleme (sn) | 0.7 |
| `--no-headless` | Tarayıcıyı görünür aç | kapalı |
| `--export` | JSONL → `tarifler/<kategori>-NNN.json` (her biri ≤20.000 tarif) | — |

## Hız sınırı

Site Cloudflare arkasında ve çok hızlı isteklere 403 döndürüyor. Bot istekleri tek tek gönderir;
istekler başarılı oldukça yavaşça hızlanır, 403/429 alınca yavaşlar ve arka arkaya gelirse
5–30 dakika ara verir. Alınamayan tarif olursa o sayfa tamamlanmış sayılmaz ve tekrar denenir.

## Eleme kuralları

`--export` sırasında işe yaramayacak kayıtlar elenir ve sayıları `tarifler/ozet.json` içinde `elenen_tarif` altında tutulur:

- isimsiz veya geçersiz linkli kayıtlar
- 2'den az malzemesi olan tarifler
- bozuk malzeme listeleri (60'tan fazla satır ya da paragraf halinde yazılmış malzeme)
- aynı link veya aynı isim + aynı malzemelerle tekrar eden tarifler

## Çıktı formatı

GitHub'ın 100 MB dosya sınırı nedeniyle veri kategori başına parçalara bölünür; `tarifler/ozet.json` toplam sayıları içerir.

```json
{
  "kaynak": "https://www.nefisyemektarifleri.com",
  "kategori": "et-yemekleri",
  "parca": 1,
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
