# WANPIS — Wahana Production Analysis Information System

Aplikasi web untuk kinerja alat dan produksi tambang per site. Sumber datanya workbook bulanan **Data_Prod** (.xlsb/.xlsx) ditambah target bulanan per site.

Isinya:

- Dashboard: PA, UoA, time distribution, reliability (MTBS, MTTR, PM accuracy), produksi OB dan coal, productivity loader dan hauler, fuel, data quality.
- Alur import, approval, dan versi data.
- Layar TV per site untuk control room.

Stack: Python 3.13 · Streamlit · PostgreSQL · SQLAlchemy/Alembic · Plotly · pandas (reader calamine).

---

## Daftar isi

1. [Menjalankan di PC (lokal)](#1-menjalankan-di-pc-lokal)
2. [Pemakaian sehari-hari](#2-pemakaian-sehari-hari)
3. [Pasang layar TV](#3-pasang-layar-tv)
4. [Deploy ke server (Docker, VPS)](#4-deploy-ke-server-docker-vps)
5. [Backup & restore](#5-backup--restore)
6. [Perintah CLI](#6-perintah-cli)
7. [Test & kualitas kode](#7-test--kualitas-kode)
8. [Troubleshooting](#8-troubleshooting)
9. [Struktur folder](#9-struktur-folder)

---

## 1. Menjalankan di PC (lokal)

### Kebutuhan

| Komponen | Versi | Catatan |
|---|---|---|
| Python | 3.13 | centang *Add to PATH* saat instal |
| PostgreSQL | 16 atau lebih baru | di Windows paling mudah lewat **Laragon** (menu *Menu → PostgreSQL → Start*) |
| Git | versi apa saja | opsional, untuk ambil / update kode |

Microsoft Excel **tidak** diperlukan. File .xlsb dibaca langsung oleh aplikasi.

### Langkah 1 — Siapkan database

Buka terminal PostgreSQL (Laragon: *Menu → PostgreSQL → psql*, atau `psql -U postgres`), lalu buat user dan dua database (satu untuk aplikasi, satu untuk test):

```sql
CREATE USER eq_app WITH PASSWORD 'ganti-dengan-password-kuat';
CREATE DATABASE eq_dashboard      OWNER eq_app;
CREATE DATABASE eq_dashboard_test OWNER eq_app;
```

### Langkah 2 — Instal aplikasi

Jalankan dari folder `eq_dashboard`:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

Untuk pengembangan (test dan linter), pakai `pip install -r requirements-dev.txt`.

### Langkah 3 — Isi file `.env`

Salin `.env.example` menjadi `.env`, lalu isi:

```ini
DATABASE_URL=postgresql+psycopg://eq_app:PASSWORD@127.0.0.1:5432/eq_dashboard
TEST_DATABASE_URL=postgresql+psycopg://eq_app:PASSWORD@127.0.0.1:5432/eq_dashboard_test
AUTH_COOKIE_KEY=...                  # rahasia acak, minimal 32 karakter
STREAMLIT_SERVER_COOKIE_SECRET=...   # rahasia acak lain
```

Buat nilai acak untuk kedua kunci dengan:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> `AUTH_COOKIE_KEY` menandatangani cookie login. Aplikasi menolak jalan kalau kunci lebih pendek dari 32 karakter atau masih `CHANGE_ME…`. File `.env` **tidak boleh** di-commit.

### Langkah 4 — Buat tabel dan admin pertama

```bash
python cli.py migrate          # membuat / memperbarui semua tabel
python cli.py create-admin     # tanya username, nama, dan password (tidak tampil di layar)
```

Password minimal 10 karakter dan harus berisi campuran huruf dengan angka atau simbol.

### Langkah 5 — Isi data awal (opsional, bisa juga lewat web)

```bash
python cli.py import-target ..\Target.xlsx            # target bulanan (ke semua site)
python cli.py ingest ..\Data_Prod_2026-09.xlsb        # import satu bulan
python cli.py status                                  # lihat status per site
python cli.py approve <id>                            # publish satu site (id dari 'status')
```

### Langkah 6 — Jalankan

```bash
run_local.bat
# atau:
streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Buka **http://127.0.0.1:8501** lalu login dengan akun admin.

Dengan `--server.address 127.0.0.1`, aplikasi hanya bisa dibuka dari PC ini. Supaya bisa diakses PC lain di jaringan kantor, pakai `--server.address 0.0.0.0` dan buka port 8501 di firewall. Untuk akses dari luar kantor, pakai deploy Docker dengan HTTPS (bagian 4).

---

## 2. Pemakaian sehari-hari

### Peran pengguna

| Peran | Bisa apa |
|---|---|
| **Admin** | semua: user & role, site & mapping, target & plan, interval PM, TV devices, audit log, hapus data |
| **Site Manager** | dashboard site-nya, approve/reject data site-nya, target & plan site-nya, preview TV, export Data_Prod |
| **Data Officer** | import Data_Prod, dashboard, Data explorer, export |
| **Viewer** | dashboard dan Data explorer untuk site yang diberikan (data PUBLISHED saja) |
| **Display** | link TV bertoken rahasia, terkunci ke satu site, hanya membuka layar TV |

Admin membuat user di **Admin → Users & roles**. Password sementara hanya ditampilkan sekali, dan user wajib menggantinya saat login pertama.

### Update data bulanan

1. Lengkapi workbook **Data_Prod** di Excel seperti biasa (month to date).
   - Nama file yang disarankan: `Data_Prod_YYYY-MM.xlsb`, misalnya `Data_Prod_2026-09.xlsb`.
   - Belum punya format? Unduh template di **Data → Data_Prod → Template**. Template berisi README, penjelasan tiap kolom, drop-down, dan validasi input.
2. Buka **Data → Data_Prod → Import** dan pilih file.
   - Aplikasi mengecek struktur file lalu menampilkan ringkasan per sheet dan per site, beserta temuan data quality.
   - Tidak ada yang tersimpan sebelum tombol **Submit for approval** ditekan.
3. Site Manager meng-approve di **Data → Approval**.
   - Kalau *auto-approve* aktif untuk site itu dan tidak ada temuan kritis, data langsung PUBLISHED.
4. Setelah PUBLISHED, semua dashboard langsung memakai data baru, dan layar TV ikut berubah paling lambat sekitar 5 menit.

Upload ulang bulan yang sama akan membuat **versi baru**. Versi lama tetap tersimpan di *Upload history* dan Admin bisa melakukan rollback.

**Mengoreksi data:** buka **Data_Prod → Export**, pilih bulan dan site, perbaiki file di Excel, lalu import lagi.

### Filter dashboard

- **Period:** Last complete day · Last 7 days · Month to date · Last month · Year to date · Custom range. Rentang boleh melewati batas bulan.
- **Filter lain:** Site, Week of month, Shift, Type → Model → Unit ID.
- **Filter ikut tersimpan di URL.** Filter tetap ada setelah reload, dan link bisa dibagikan. Hak akses penerima tetap berlaku.
- **Save as default** menyimpan filter favorit per user. **Reset** mengembalikan filter ke setelan awal.

### Data mentah

**Data → Data explorer** menampilkan baris mentah hasil olahan (events, ritase, coal, fuel, dan lain-lain), lengkap dengan nomor **Excel row** asal. Hasilnya bisa diunduh sebagai CSV atau Excel.

---

## 3. Pasang layar TV

1. Admin membuka **Admin → TV devices**, isi nama TV, site, dan periode (hourly/daily/weekly/monthly/yearly), lalu klik **Create TV link**.
2. Salin link yang muncul. Link hanya ditampilkan **sekali**.
3. Di mini-PC atau TV, jalankan browser dalam mode kiosk:

   ```bash
   msedge --kiosk "https://dashboard.perusahaan.co.id/?display=TOKEN" --edge-kiosk-type=fullscreen
   # atau: chrome --kiosk "https://…/?display=TOKEN"
   ```

4. Aktifkan auto-start saat PC menyala, lalu matikan *sleep* dan screensaver.

Layar didesain untuk 1920×1080, satu layar tanpa scroll, dan refresh otomatis tiap 5 menit. Link bisa dicabut atau dibuat ulang kapan saja dari halaman yang sama. Status online setiap TV juga terlihat di **Data status → System health**.

---

## 4. Deploy ke server (Docker, VPS)

Kebutuhan server: Linux dengan Docker + Docker Compose, domain yang mengarah ke IP server, serta port 80 dan 443 terbuka. Caddy mengurus sertifikat HTTPS secara otomatis.

```bash
# di server
git clone <repo> /opt/eq_dashboard-src
cp -r /opt/eq_dashboard-src/eq_dashboard /opt/eq_dashboard
cd /opt/eq_dashboard
cp deploy/.env.example deploy/.env
nano deploy/.env          # isi DOMAIN, POSTGRES_PASSWORD, AUTH_COOKIE_KEY, STREAMLIT_SERVER_COOKIE_SECRET
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec app python cli.py create-admin
```

Yang disiapkan oleh file deploy:

- **db:** PostgreSQL, hanya bisa diakses dari jaringan internal Docker (tidak ada port yang dibuka ke luar).
- **app:** berjalan sebagai user non-root. Migrasi database (`alembic upgrade head`) berjalan otomatis setiap start, dan ada healthcheck.
- **caddy:** HTTPS, header keamanan, kompresi, dan batas upload 50 MB.
- **Log:** maksimal 5 × 10 MB per container.

**Update versi aplikasi:**

```bash
cd /opt/eq_dashboard-src && git pull
rsync -a --delete --exclude deploy/.env eq_dashboard/ /opt/eq_dashboard/
cd /opt/eq_dashboard && docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

**Melihat log:** `docker compose -f deploy/docker-compose.yml logs -f app`

---

## 5. Backup & restore

Backup harian memakai `deploy/backup.sh`. Hasilnya disimpan di `/var/backups/eq_dashboard` selama 14 hari. Pasang cron di server:

```bash
chmod +x /opt/eq_dashboard/deploy/backup.sh
crontab -e
# tambahkan:
15 2 * * * /opt/eq_dashboard/deploy/backup.sh >> /var/log/wanpis-backup.log 2>&1
```

Setiap dump diverifikasi sebelum disimpan. Hasil setiap run (berhasil atau gagal) tercatat di aplikasi dan terlihat di **Data status → System health**. Kartu *Last backup* berwarna oranye kalau run terakhir gagal atau sudah lebih dari 36 jam.

**Restore** (menimpa isi database):

```bash
cd /opt/eq_dashboard
docker compose -f deploy/docker-compose.yml --env-file deploy/.env stop app
docker compose -f deploy/docker-compose.yml --env-file deploy/.env exec -T db \
  pg_restore -U eq_app -d eq_dashboard --clean --if-exists < /var/backups/eq_dashboard/eq_dashboard_2026-09-28.dump
docker compose -f deploy/docker-compose.yml --env-file deploy/.env start app
```

Simpan juga file Excel asli setiap bulan. Semua data bisa dibangun ulang dengan meng-import ulang file-file itu.

---

## 6. Perintah CLI

Jalankan dari folder `eq_dashboard` (di Docker, awali dengan `docker compose … exec app`):

| Perintah | Fungsi |
|---|---|
| `python cli.py migrate` | buat / perbarui tabel |
| `python cli.py create-admin` | admin pertama (password ditanya tanpa tampil) |
| `python cli.py create-user budi --name "Budi" --role site_manager --site WBK-MAS` | tambah user; role: `admin`, `site_manager`, `data_officer`, `viewer`; `--all-sites` untuk semua site |
| `python cli.py reset-password budi` | password sementara, wajib diganti saat login |
| `python cli.py ingest <file.xlsb>` | import satu workbook Data_Prod |
| `python cli.py import-target Target.xlsx [--site WBK-MAS]` | import target bulanan |
| `python cli.py status` | daftar upload dan status per site |
| `python cli.py approve <id>` | publish satu site dari sebuah upload |

---

## 7. Test & kualitas kode

```bash
pip install -r requirements-dev.txt
pytest                 # butuh TEST_DATABASE_URL; ±10 menit
ruff check .           # linter (aturan di pyproject.toml)
```

Sebagian test memakai file contoh `../Eq.Event.xlsb` dan `../Target.xlsx`. Test itu otomatis dilewati kalau filenya tidak ada. File data (.xlsb/.xlsx/.pdf) tidak di-commit.

---

## 8. Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| `AUTH_COOKIE_KEY must be a random secret…` | isi kunci acak minimal 32 karakter di `.env` (lihat langkah 3) |
| `DATABASE_URL is not set` | file `.env` belum ada atau salah folder; harus di `eq_dashboard/.env` |
| `connection refused` ke database | PostgreSQL belum jalan (Laragon: *Start*), atau host/port/password di `DATABASE_URL` salah |
| Error `relation … does not exist` | jalankan `python cli.py migrate` |
| Perubahan kode di `core/` tidak terlihat | restart server; Streamlit hanya memuat ulang file halaman, bukan modul `core/` |
| Terlogout setiap refresh | pastikan `AUTH_COOKIE_KEY` tidak berubah-ubah, lalu login ulang sekali |
| File ditolak saat import | pesan menyebut sheet/kolom yang salah; bandingkan dengan **Template** (nama sheet & header harus sama persis) |
| Dashboard kosong setelah import | data masih PENDING; approve di **Data → Approval** |
| Layar TV "link invalid or revoked" | link dicabut / dibuat ulang; ambil link baru di **Admin → TV devices** |
| Port 8501 sudah dipakai | hentikan proses lama, atau jalankan dengan `--server.port 8502` |

---

## 9. Struktur folder

```
eq_dashboard/
  app.py                 entrypoint: login → menu per role; ?display=<token> → layar TV
  cli.py                 perintah administrasi
  auth/                  login (streamlit-authenticator + bcrypt), role & akses site, token TV
  core/                  logika tanpa UI
    io.py, validate.py   baca workbook (calamine) & spesifikasi kolom Data_Prod
    clean.py, parse.py   cleaning per sheet → tabel fakta per site
    metrics.py, dq.py    PA/UoA/MTBS/MTTR…, pemeriksaan data quality
    ingest.py            simpan upload, versi, approve/reject/rollback
    dataprod.py          template & export Data_Prod
    filters.py           preset periode, filter di URL
    tv.py, tv_render.py  data & tampilan layar TV
    dash.py, theme.py    filter sidebar, target, chart, design tokens
  db/                    model SQLAlchemy, query, migrasi Alembic
  pages/                 halaman Streamlit (dashboard, data, admin, tv)
  static/                font IBM Plex Sans, logo
  deploy/                Dockerfile, docker-compose.yml, Caddyfile, backup.sh
  tests/                 pytest (golden test terhadap angka Excel, akses, round-trip)
```

Rencana lengkap dan riwayat keputusan desain ada di `../plan.md`.
