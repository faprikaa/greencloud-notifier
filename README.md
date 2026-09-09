# GreenCloud VPS → Telegram

Notifier ringan Python + Docker Compose untuk lima produk (empat GreenCloud dan satu Kainode):

- [BudgetKVMSGDC1-2](https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsgdc1-2)
- [BudgetKVMSGDC1-3](https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsgdc1-3)
- [BudgetKVMSG-3 DC2](https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsg-3)
- [BudgetKVMSG-2 DC2](https://greencloudvps.com/billing/store/budget-kvm-sale/budgetkvmsg-2)

- [Kainode VPS Advanced Singapore](https://portal.kainode.com/products/vps-singapore/vps-advanced)

Kainode memakai detektor tersendiri: judul VPS Advanced, badge `In stock`, dan link checkout produk yang tepat harus ada. Penanda `Product VPS Advanced is out of stock` berarti habis. Struktur positif dibandingkan dengan halaman VPS Pro Kainode yang tersedia, tetapi VPS Advanced sendiri belum teramati tersedia.

**Setiap pengecekan yang menemukan stok tersedia mengirim pesan lagi.** Tidak ada deduplikasi, cooldown stok, atau database. Lima produk tersedia berarti sampai lima pesan per siklus. Tidak membeli VPS otomatis.

## 1. Buat bot Telegram

1. Buka **@BotFather** resmi di Telegram, jalankan `/newbot`, simpan token.
2. Buka chat dengan bot buatanmu, tekan **Start**, lalu kirim pesan.
3. Temukan chat ID menggunakan `getUpdates` di komputer sendiri. Contoh berikut meminta token tanpa menampilkannya atau menyimpannya di shell history:

```bash
python3 - <<'PY'
import getpass, json, urllib.request
from urllib.error import URLError
secret = getpass.getpass('Bot token: ')
try:
    with urllib.request.urlopen('https://api.telegram.org/bot' + secret + '/getUpdates', timeout=20) as r:
        data = json.load(r)
    for update in data.get('result', []):
        chat = update.get('message', {}).get('chat', {})
        if chat:
            print('Chat ID:', chat['id'], 'Type:', chat.get('type'))
except URLError:
    print('Gagal menghubungi Telegram. Periksa token/koneksi secara lokal.')
PY
```

Jika hasil kosong, kirim pesan baru ke bot lalu ulangi. Gunakan bot khusus: `getUpdates` tidak bekerja jika bot sedang menggunakan webhook. Untuk grup, tambahkan bot dan kirim command yang ditujukan kepadanya; ID grup biasanya negatif. Jangan bagikan token atau output API lengkap.

## 2. Jalankan Docker

Butuh Docker Engine dan plugin Compose.

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=isi_token_dari_botfather
TELEGRAM_CHAT_ID=isi_chat_id
CHECK_INTERVAL_SECONDS=60
```

Kemudian:

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

Perubahan `.env` diterapkan dengan `docker compose up -d --force-recreate`.

Berhenti:

```bash
docker compose down
```

Tidak membutuhkan volume. Container non-root, filesystem read-only, log dirotasi. Token tidak dimasukkan ke image; tetap perlakukan akses Docker host sebagai akses ke rahasia container.

## Perilaku pengecekan

- Saat startup/restart, kirim **pesan tes Telegram** terlebih dahulu untuk memastikan bot dapat mengirim ke chat ID tujuan. Pesan tes bukan notifikasi stok. Pemantauan hanya dimulai setelah Telegram mengonfirmasi pengiriman berhasil. Kalau gagal, periksa token, chat ID, apakah chat bot sudah di-Start, izin grup, dan koneksi; aplikasi mencoba lagi dengan backoff tanpa memulai pengecekan stok.
- Setelah tes Telegram berhasil, cek stok lalu tunggu default **60 detik setelah satu siklus selesai**. Waktu HTTP menambah jarak antarcek; bukan jadwal tepat setiap menit.
- Interval minimum 30 detik. HTTP timeout connect/read 5/20 detik, respons maksimum 2 MiB.
- `available`: formulir konfigurasi WHMCS dengan identitas produk yang cocok dan tombol lanjut aktif → kirim Telegram.
- `unavailable`: penanda **Out of Stock** pada area order → tidak kirim.
- `unknown`: error, redirect, halaman proteksi, atau HTML tidak dikenali → tidak kirim. Lihat log untuk diagnosis.
- Link **Order Now di kategori tidak cukup**: GreenCloud menampilkannya juga pada produk habis.
- Pengiriman Telegram gagal tidak disimpan sebagai antrean. Dicoba lagi pada cek berikutnya yang memastikan stok tersedia.
- Ada jeda 1 detik setelah pengiriman. Gangguan jaringan memakai backoff 2/4/8/15 menit, tidak lebih pendek daripada interval konfigurasi. `Retry-After` dihormati sampai batas satu jam.
- Batas API Telegram tetap dihormati; tidak ada upaya melewati proteksi situs.

## Batas verifikasi

**Hasil verifikasi lingkungan pengembangan:** 23 tes offline lolos dan konfigurasi Compose valid. Build image belum terverifikasi karena Docker daemon tidak aktif. Request live dengan Python requests mendapat HTTP 403 untuk keempat produk; aplikasi mengembalikannya sebagai `unknown`. Karena itu pemantauan live belum terbukti bekerja dari lingkungan ini. Jalankan di host tujuan dan periksa log; bila 403 berlanjut, minta jalur akses/API yang diizinkan GreenCloud, jangan menganggap layanan sedang memantau stok dengan sukses.

Keempat halaman produk saat inspeksi awal melalui curl menampilkan **Out of Stock**. Deteksi negatif berdasarkan HTML asli. Fixture positif mengikuti struktur standar WHMCS, tetapi **belum diverifikasi terhadap produk target yang benar-benar tersedia**. Jika tema/form berubah, hasil sengaja menjadi `unknown` daripada memberi notif palsu. Tidak ada jaminan stok masih ada saat link dibuka. Pengiriman Telegram langsung memerlukan token dan chat ID milikmu.

## Tes lokal (tanpa Telegram/network)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q notifier tests
```

Menjalankan tanpa Docker juga bisa: ekspor ketiga environment variable lalu `.venv/bin/python -m notifier`. Aplikasi tidak otomatis membaca `.env` di luar Compose.
