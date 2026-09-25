# Rencana: Dashboard Eq Event & Produksi (multi-site, multi-user)

> Dibuat: 2026-09-25 · **Revisi 6** (keputusan review + Target.xlsx + perbaikan context7 + **tampilan TV per site**).
> Sumber data: **`Eq.Event.xlsb`** per bulan + **`Target.xlsx`**. Referensi gaya visual: `Report 20260723.pdf`.
> Blueprint review: https://claude.ai/artifact/K5N7pzdZz4W9ktgyixopaZ

## Konteks
Saat ini `Eq.Event.xlsb` diolah manual dengan rumus Excel (SUMIFS di sheet `Summary`) untuk PA/UoA. Tujuannya adalah aplikasi web di **cloud/VPS** yang:
- menerima upload file Eq.Event (update harian/mingguan, month-to-date, histori multi-bulan),
- membersihkan data & memecahnya **per site** (site dari kolom `Site` di Populasi Unit: WBK-MAS, WBK-BAU, dst.),
- menampilkan dashboard yang bisa difilter **satu site, beberapa site, atau All Site** sesuai hak akses user,
- membandingkan actual dengan **target bulanan per site** (PA, UoA, MTBS, MTTR, Scheduled Down, PM Accuracy),
- punya **4 user role** dengan alur approval sebelum data tampil ke management,
- **tampil di TV (web) di setiap site**: satu layar Full HD yang memuat semua ringkasan penting, terbaca dari jauh, refresh otomatis, tanpa perlu disentuh. Ini adalah target utama tampilan aplikasi.

Isi dashboard: Eq Event (PA, UoA, Time Distribution) per Type / Model / Unit ID, Reliability (MTBS, MTTR, Scheduled Down, PM Accuracy), Produksi OB (ritase) & Coal Getting (timbangan), Loader & Fleet, Fuel, Data Quality.
Data biaya part/budget/oli di report PDF **tidak ada** di Eq.Event → di luar scope v1.

## Hasil studi data

### Eq.Event.xlsb (1–23 Sep 2026)
| Sheet | Isi | Catatan |
|---|---|---|
| Populasi Unit (332) | master unit: Type, Description, Model, Manufacturer, **Site** (WBK-MAS 173, WBK-BAU 154, kosong 5) | kunci = `Equipment` |
| Eq.Event (62.228) | event per unit/shift: Date, Shift, Unit ID, Jam Awal/Akhir, Total Jam, HM awal/akhir, Status, Reason | kolom A–K rumus turunan; 185 unit |
| Ritasi Unit (3.361) | header baris 2; rit per jam (06-07 … 05-06) hauler×loader×material×lokasi×disposal, Muatan, jarak H/V | 32.893 rit; OB 778.796 BCM; CG 95.124 t |
| Data Timbangan (3.491) | tiket coal: DT, loader, seam, gross/tare/netto, `Tone`, jam masuk/keluar | 94.855,44 t |
| Fuel Consume (4.174) / Fuel Receipt (121) | pengisian per unit; penerimaan per DO | 1.380.293 L vs 1.189.002 L |
| Summary | PA/UoA per Week, Type×Week, Unit×Week + pivot "Act PA" | acuan golden test |

Rumus Excel yang direproduksi persis: **PA = (R+I+S)/T**, **UoA = (R+I)/(R+I+S)**; R=Operating, I=Idle, S=Standby, D=SM+USM. Reason code: 1xx Operating, 2xx Idle, 3xx Standby, 4xx USM, 5xx SM (502 = Periodic Service PM).

### Target.xlsx
- Satu sheet, kolom: `Year, Month, Target PA, Target UoA, MTBS Target, MTTR Target, Sched. Down Target, PM Accuracy Target`; 94 baris (Sep 2018 – Sep 2026), **tanpa kolom Site**.
- Nilai tetap: UoA 60%, MTBS 90 jam, MTTR 15 jam, Sched. Down 60%, PM Accuracy 100%. Target PA bervariasi (80,6–92,8%).
- **Target PA kosong Mar–Sep 2026**; bulan 2018-10, 2020-12, 2026-02 tidak ada.
- Tidak berisi plan produksi.

### Pemetaan site (dicek pada data Sep)
| Sheet | Site dari | Temuan |
|---|---|---|
| Eq.Event, Fuel Consume | site unit | 1 unit event & 7 unit fuel tanpa site |
| Ritasi | **site loader** (site hauler disimpan) | lintas site ±11.200 BCM (1,3%) |
| Timbangan | **site loader** (site DT disimpan) | lintas site 11.583 t; 984 t loader tak dikenali |
| Fuel Receipt | site fuel truck / mapping tangki | TANKI-02/03/04 (160.000 L) tanpa site |

Site dibaca dari sheet Populasi **di file bulan itu sendiri** (snapshot per bulan). Baris tanpa site → `UNMAPPED` (hanya terlihat Admin sampai dipetakan).

### Preview actual vs target (Sep 2026, All Site)
| Metrik | Actual | Target | | MAS | BAU |
|---|---|---|---|---|---|
| PA | 65,3% | belum ada target | | 71,1% | 54,5% |
| UoA | 47,3% | 60% | | 51,3% | 39,4% |
| MTBS (SM+USM) | 20,5 jam | 90 jam | | 21,7 | 17,7 |
| MTTR (SM+USM) | 23,0 jam | 15 jam | | 17,2 | 37,5 |
| Scheduled Down | 12,4% | 60% | | 12,3% | 12,6% |
| Stoppage | 1.489 | — | | 1.061 | 425 |

> Koreksi 2026-09-26: angka stoppage awal (1.606) salah karena urutan event shift malam; dengan urutan kronologis yang benar = 1.489.

### Masalah data (ditangani di cleaning + halaman Data Quality)
- `Event Down` selalu kosong (bug rumus) → diturunkan ulang dari Status + Reason.
- 23 baris Status/Total Jam kosong; 16 unit-hari 48 jam; 62 unit-hari 12 jam.
- Unit tidak ada di Populasi / tanpa site; tangki tanpa site.
- Pivot "Act PA" rata-rata tanpa bobot → PA berbobot jam (UoA 47,3% vs 44,1% di Summary).
- Timbangan: shift `day/Day/Night`, supplier `BATAL`, loader `WE030` / `WEX032 `, Netto campur kg/ton.
- Fuel: 1 volume kosong, pengisian ekstrem (s/d 6.201 L).
- Excel COM di PC ini rusak → baca .xlsb dengan `pyxlsb`.

### File yang dipelajari tapi tidak dipakai
`Populasi Unit.xlsx` (identik dengan sheet Populasi), `Prod.Act 202607.xlsb` (data sama dengan Ritasi dalam bentuk volume; potongan 3 loader/14 hari).

## Keputusan (hasil review)
| # | Topik | Keputusan |
|---|---|---|
| 1 | Target | Dari **Target.xlsx**, bulanan, **per site** (format diperluas dengan kolom `Site`; file lama tanpa Site diimport lalu Admin memilih site tujuan, default semua site). Bisa diedit di aplikasi. |
| 1a | Bulan tanpa target | Tampilkan **"belum ada target"** (tanpa garis/selisih target). Tidak ada carry-forward. |
| 2 | Plan produksi | Tidak ada di Target.xlsx → diisi di aplikasi per site, harian **atau** bulanan (bulanan dibagi rata per hari kalender untuk achievement MTD). Bila kosong: tampilkan actual saja. |
| 3 | Unit down sepanjang periode | **Tetap dihitung** di PA fleet. |
| 4 | UoA | Idle tetap dihitung sebagai jam kerja (sesuai Summary). |
| 5 | Produktivitas loader | BCM / jam Ready; Ready+Idle sebagai pembanding. |
| 6 | Fuel ratio | Total per site (L / OB BCM) + rasio fleet hauling+loading / OB BCM. |
| 7 | Standby | Dikelompokkan **client vs internal** (325 Available not required, 327 Waiting client, dll = client; sisanya internal). Mapping reason→kelompok bisa diubah Admin. |
| 8 | Struktur file | Validasi struktur saat upload (nama sheet, kolom wajib, header Ritasi baris 2); file berbeda ditolak dengan pesan jelas. |
| 9 | Produksi lintas site | Dicatat ke **site loader**; site hauler/DT disimpan untuk analisa fleet. |
| 10 | Approval | Opsi **auto-approve per site** (diatur Admin) bila tidak ada temuan DQ kritis; bila ada → manual. |
| 11 | Cloud & domain | Diputuskan saat production. Pengembangan & uji berjalan lokal dengan Docker Compose. |
| 12 | Notifikasi | **Cukup di aplikasi** (antrian + badge), tanpa email. |
| — | MTBS / MTTR | Stoppage = **semua down (SM + USM)**. MTBF (USM saja) tetap ditampilkan sebagai tambahan. |
| — | PM Accuracy | Dari **interval HM per model**: PM (reason 502) akurat bila selisih HM sejak PM sebelumnya dalam interval ± toleransi. Interval & toleransi per model diisi Admin. |
| TV | Login TV | Role ke-5 **Display**: link TV bertoken rahasia, terkunci ke 1 site, hanya membuka layar TV, read-only, bisa dicabut Admin. |
| TV | Mode layar | **Satu layar padat** 16:9 tanpa scroll dan tanpa rotasi. |
| TV | Periode | **MTD** bulan berjalan vs target + angka **hari lengkap terakhir** + trend harian. |
| TV | Resolusi | Didesain untuk **Full HD 1920×1080**, diskalakan proporsional di TV 4K. |

Keputusan lain yang tetap: stack Python/Streamlit/PostgreSQL; site dari kolom Site Populasi; 4 role; login username & password; PA/UoA berbobot jam; minggu 1–7/8–14/15–21/22–akhir; OB dalam BCM, CG dalam ton (tidak dijumlahkan).

## Definisi metrik
- W = R + I; T = R + I + S + D.
- **PA** = (W+S)/T · **UoA** = W/(W+S) · **MA** = W/(W+D) · **EU** = W/T. Σ jam dulu baru dibagi (juga lintas site).
- **Stoppage** = blok down (SM atau USM) berurutan per unit; blok yang bersambung lintas shift/hari = 1 stoppage.
- **MTBS** = W / jumlah stoppage · **MTTR** = jam D / jumlah stoppage · **MTBF** = W / jumlah stoppage USM.
- **Scheduled Down** = jam SM / jam D.
- **PM Accuracy** = PM akurat / PM yang bisa dinilai. PM pertama per unit (tanpa PM sebelumnya dalam histori) tidak dinilai. HM diambil dari `HM awal` pada event 502.
- Standby client vs internal = jam S per kelompok reason.
- Produktivitas loader = BCM / jam Ready (pembanding: / jam Ready+Idle); hauler = rit & BCM / jam Ready.
- Fuel ratio = L / OB BCM per site, dan L fleet hauling+loading / OB BCM; L / jam HM per unit.
- Plan vs actual produksi: achievement MTD & proyeksi akhir bulan per site.

## Tampilan TV per site (target utama)
Setiap site memasang TV dengan browser mode kiosk yang membuka link Display site itu. Layar tidak disentuh sama sekali.

**Layout 1920×1080, satu layar, tanpa scroll** (contoh angka WBK-MAS Sep 2026):
| Zona | Isi |
|---|---|
| Header | Nama site · bulan & rentang MTD · waktu data terakhir diperbarui · status data · jam |
| Baris KPI (8 kartu) | PA, UoA, MTBS, MTTR, Scheduled Down, PM Accuracy, OB BCM, Coal ton. Tiap kartu: angka MTD besar, target, selisih (warna + panah ▲▼), angka hari lengkap terakhir |
| Tengah kiri | Trend harian PA & UoA bulan berjalan + garis target; hari yang belum lengkap diberi tanda |
| Tengah kanan | Produksi harian OB (BCM) & coal (ton) vs plan |
| Bawah (4 panel) | PA per Type vs target · time distribution per Type (R/I/S/D) · 5 komponen down terbesar · unit bermasalah (down terlama, status terakhir) |
| Footer | Jumlah unit · unit down pada data terakhir · fuel MTD & L/BCM · temuan DQ · "diperbarui otomatis tiap 5 menit" |

**Aturan tampilan TV**
- Hanya data **PUBLISHED** untuk 1 site (terkunci di token Display).
- **Hari lengkap terakhir** = tanggal terakhir di mana ≥ 95% unit aktif punya data kedua shift. Contoh Sep: tgl 23 baru berisi 3 dari 119 unit MAS, jadi TV memakai 22 Sep (PA 72,7%, UoA 28,1%). Hari yang belum lengkap tetap ditampilkan di trend dengan tanda "belum lengkap", tapi tidak dipakai untuk kartu "hari terakhir".
- Refresh otomatis dengan `@st.fragment(run_every="5m")`; data baru yang di-approve muncul paling lambat ±5 menit (cache dibersihkan saat approve).
- Tema gelap kontras tinggi, font besar (angka KPI ±64 px, label ±20 px pada 1080p), status tidak hanya lewat warna (ada panah & teks), aman untuk buta warna.
- Tanpa elemen interaktif: sidebar, header Streamlit, dan toolbar disembunyikan (`st.navigation(position="hidden")`, `client.toolbarMode="minimal"`, `initial_sidebar_state="collapsed"`, CSS tambahan untuk padding/header).
- Bila koneksi putus, Streamlit menyambung ulang otomatis; layar menampilkan "terakhir diperbarui" supaya data basi terlihat.
- Ukuran grafik Plotly ditetapkan untuk 1080p; skala proporsional di 4K lewat zoom browser kiosk.

**Akun & perangkat Display**
- Admin membuat perangkat Display: nama TV, site, lalu aplikasi menghasilkan link `https://<domain>/?display=<token>`. Token acak 32 byte, yang disimpan di DB hanya hash-nya.
- Token hanya membuka halaman TV untuk site tersebut (read-only, published saja), tanpa menu lain.
- Admin bisa mencabut atau membuat ulang token kapan saja; `last_seen` per perangkat menunjukkan TV mana yang sedang online.
- Setup TV: Chrome/Edge `--kiosk <link>`, auto-start saat TV/mini-PC menyala, nonaktifkan sleep/screensaver.
- Site Manager & Admin punya menu **Preview TV** untuk melihat tampilan TV site-nya dari aplikasi biasa.

## User role & hak akses
| Kemampuan | Admin | Site Manager | Data Officer | Viewer | Display (TV) |
|---|:-:|:-:|:-:|:-:|:-:|
| Lihat layar TV | semua site (preview) | site-nya (preview) | – | – | 1 site terkunci |
| Lihat dashboard data **approved** | semua site | site-nya | site-nya | site diberikan / All | – |
| Lihat data **pending** (preview) | ✓ | site-nya | upload miliknya | – | – |
| Upload file Eq.Event | ✓ | – | ✓ | – | – |
| Approve / reject data per site | ✓ | site-nya | – | – | – |
| Import Target.xlsx / edit target & plan | semua site | site-nya | – | – | – |
| Atur interval PM per model, mapping standby | ✓ | – | – | – | – |
| Kelola user, role, akses site, auto-approve | ✓ | – | – | – | – |
| Kelola perangkat Display (buat/cabut link TV) | ✓ | – | – | – | – |
| Kelola site, alias ID, mapping tangki | ✓ | – | – | – | – |
| Rollback versi data | ✓ | – | – | – | – |
| Lihat audit log | ✓ | site-nya | – | – | – |
| Unduh Excel | ✓ | ✓ | ✓ | ✓ | – |

Semua akses data melewati satu fungsi `scope_filter(user, df)` di server.

## Alur upload & approval
1. Data Officer upload `Eq.Event.xlsb` → cek SHA-256 (file identik ditolak) → **validasi struktur** → parse & cleaning → data dipecah per site.
2. Ringkasan per site (jam, rit, ton, liter) + DQ ditampilkan → Submit.
3. Per site: bila auto-approve aktif **dan** tidak ada DQ kritis → langsung `PUBLISHED`; selain itu `PENDING` dan muncul di antrian Site Manager (badge in-app).
4. Site Manager preview dashboard & DQ → Approve (`PUBLISHED`, versi lama `SUPERSEDED`) atau Reject + komentar.
5. Viewer hanya melihat versi `PUBLISHED` terbaru per site × bulan. Admin bisa rollback. Semua aksi masuk `audit_log`.

## Struktur aplikasi (`eq_dashboard/`)
```
eq_dashboard/
  app.py                     # entrypoint: ?display=token → layar TV (navigasi hidden); selain itu auth → st.navigation per role
  .streamlit/config.toml     # konfigurasi server & keamanan (lihat "Konfigurasi")
  auth/
    authenticator.py         # streamlit-authenticator: credentials dari tabel users, cookie JWT, max_login_attempts
    access.py                # ROLE_PAGES, require_role() guard di tiap halaman, scope_filter(user, df)
    display.py               # validasi token Display (hash), kunci site, update last_seen
  db/
    engine.py                # create_engine psycopg3, di-cache dengan @st.cache_resource
    models.py                # SQLAlchemy 2.0 declarative
    repo.py                  # query published/pending sesuai scope; cache per site × bulan × versi
    migrations/              # Alembic
  core/
    io.py                    # pd.read_excel(engine="pyxlsb", sheet_name=[…]) sekali baca; konversi serial Excel
    validate.py              # cek struktur file (sheet & kolom wajib)
    clean.py                 # normalisasi, site per baris
    ingest.py                # upload → validate → clean → split site → bulk insert 1 transaksi → status
    metrics.py               # PA, UoA, MA, EU, stoppage, MTBS, MTTR, MTBF, Sched Down, PM Accuracy
    production.py · fuel.py · dq.py · targets.py (import Target.xlsx, lookup target per site × bulan)
    ui.py                    # kartu KPI (actual vs target / "belum ada target"), ranking, export Excel
  pages/
    tv/         tv_display.py        # layar TV 1080p, @st.fragment(run_every="5m"), CSS kiosk; juga dipakai Preview TV
    dashboard/  overview · pa_ua · time_distribution · reliability · production_ob · coal_getting · loader_fleet · fuel · data_quality
    data/       upload · approval · upload_history
    admin/      targets_plan · users_roles · display_devices · sites_mapping · pm_interval · audit_log
  core/tv.py                 # hitung paket data TV per site: KPI MTD vs target, hari lengkap terakhir, trend, panel bawah
  cli.py                     # create-admin, reset-password, import-target, backup
  tests/                     # pytest + streamlit.testing AppTest
  deploy/  Dockerfile · docker-compose.yml · Caddyfile · .env.example · backup.sh
  requirements.txt           # versi dipin: streamlit, streamlit-authenticator, pandas, pyxlsb, openpyxl, plotly,
                             # sqlalchemy>=2, psycopg[binary]>=3, alembic, bcrypt, pytest
```

### Tabel database (PostgreSQL)
- **Akses**: `users` (username, nama, password_hash, role, all_sites, aktif, wajib_ganti_password, gagal_login, terkunci_sampai, last_seen), `sites` (kode, nama, aktif, auto_approve), `user_sites`, `display_devices` (nama TV, site, token_hash, aktif, dibuat_oleh, last_seen).
- **Upload**: `uploads` (file, sha256, bulan, uploader, waktu), `upload_sites` (status PENDING/PUBLISHED/REJECTED/SUPERSEDED, reviewer, waktu, komentar, ringkasan DQ, auto_approved).
- **Data** (semua punya `upload_id`, `site`, `month`): `dim_unit`, `fact_event`, `fact_stoppage` (turunan: unit, mulai, selesai, jam, SM/USM, komponen), `fact_ritase_jam` (site_loader, site_hauler), `fact_coal_tiket` (site_loader, site_dt), `fact_fuel`, `fact_fuel_receipt`, `dq_findings`.
- **Konfigurasi**: `targets` (site, tahun, bulan, pa, uoa, mtbs, mttr, sched_down, pm_accuracy — NULL = belum ada target), `plan_produksi` (site, tanggal atau bulan, ob_bcm, coal_ton), `pm_interval` (model, interval_hm, toleransi_pct), `standby_group` (reason_code → client/internal), `id_alias`, `tank_site`, `audit_log`.

## Aturan pengolahan
- **Eq.Event**: abaikan kolom rumus A–K; kategori R/I/S/D/NO DATA; Down type & komponen dari Reason; week baru; site dari unit; bangun `fact_stoppage` (blok down berurutan per unit).
- **Ritasi**: `header=1`; unpivot 24 jam → (date, jam, shift DS 06–18 / NS 18–06, rit); volume = rit × Muatan; material OB/CG/Other; site = site loader.
- **Timbangan**: buang `BATAL`; shift diseragamkan; alias loader/DT; ton = `Tone`; site = site loader.
- **Fuel**: site unit; receipt: site fuel truck atau `tank_site`; outlier > P99 per model.
- **Target.xlsx**: import per baris Year/Month(/Site); sel kosong disimpan NULL; format tanpa Site → pilih site tujuan saat import.

## Perbaikan dari riset context7 (Streamlit, streamlit-authenticator, SQLAlchemy 2.0, pandas, Caddy)
1. **Login bertahan saat refresh.** `st.session_state` hilang setiap browser di-refresh, jadi login murni di session_state memaksa user login ulang. → Pakai **streamlit-authenticator**: bcrypt, cookie re-auth (JWT HS256, key dari `.env`, `cookie_expiry_days=1`), `max_login_attempts`, field `roles`. Credentials dimuat dari tabel `users` (PostgreSQL tetap sumber kebenaran); perubahan password & gagal login ditulis balik ke DB. Idle timeout 60 menit dicek dari `last_seen`. Jalur upgrade ke SSO kantor nanti: `st.login` (OIDC).
2. **Navigasi berbasis role** dengan `st.navigation({seksi: [st.Page…]})` yang dibangun dari role, seperti tutorial "dynamic navigation" Streamlit. Halaman yang tidak didaftarkan tidak bisa dibuka. Ditambah guard `require_role()` di awal setiap halaman (defense in depth).
3. **Cache tidak boleh bocor antar user.** `@st.cache_data` berlaku global untuk semua user dan sesi. → Cache hanya dataset **per site × bulan × upload_id published** (ttl 3600). `scope_filter` diterapkan **setelah** cache, jadi hasil yang di-cache tidak pernah spesifik user. Cache dibersihkan (`func.clear()`) setelah approve, rollback, dan edit target. Engine DB di `@st.cache_resource`.
4. **Konfigurasi Streamlit** (`.streamlit/config.toml`): `server.headless=true`, `server.maxUploadSize=50` (default 200 MB), `server.enableXsrfProtection=true`, `server.cookieSecret` tetap dari env (tanpa ini upload bisa gagal 403 setelah restart atau di balik proxy), `client.showErrorDetails=false` (stack trace tidak tampil ke user), `client.toolbarMode="viewer"`, `browser.gatherUsageStats=false`.
5. **pyxlsb tidak mengenali tipe tanggal** dan mengembalikannya sebagai float. → Konversi eksplisit serial Excel (origin 1899-12-30) untuk Date, Jam Awal/Akhir (pecahan hari), dan jam masuk/keluar timbangan. Semua sheet dibaca dalam satu panggilan `read_excel(sheet_name=[…])`.
6. **Bulk insert SQLAlchemy 2.0**: `session.execute(insert(Model), records)` memakai *insertmanyvalues* (batch 1000 baris) dengan driver psycopg3. ±75 rb baris per upload masuk dalam **satu transaksi**, jadi upload yang gagal tidak meninggalkan data setengah jadi. Parsing ditampilkan dengan `st.status` karena bisa 20–40 detik.
7. **Caddy**: `reverse_proxy app:8501` meneruskan WebSocket Streamlit secara otomatis. Ditambah blok `header` (HSTS, `X-Content-Type-Options nosniff`, `X-Frame-Options DENY`, `Referrer-Policy`) dan `request_body max_size 50MB`, selaras dengan batas upload.
8. **Pengujian UI** dengan `streamlit.testing.v1.AppTest`: set `session_state` role, lalu pastikan halaman yang tampil sesuai role, halaman admin menolak non-admin, dan login salah 5x mengunci akun.
9. **Layar TV**: `@st.fragment(run_every="5m")` me-refresh hanya isi layar tanpa interaksi user; `st.navigation(position="hidden")` + `client.toolbarMode="minimal"` + `st.set_page_config(layout="wide", initial_sidebar_state="collapsed")` menyembunyikan semua elemen navigasi; token Display dibaca dari `st.query_params`.

## UI
- Login → menu per role. Sidebar: **Site (multi-select + All)**, Bulan, rentang tanggal, Week, Shift, Type → Model → Unit ID.
- >1 site dipilih: KPI gabungan (berbobot) + perbandingan antar site. Target gabungan untuk >1 site = rata-rata target site berbobot jam kalender (PA/UoA) atau dijelaskan per site (MTBS/MTTR).
- Kartu KPI menampilkan actual, target, dan selisih (hijau/merah); bulan tanpa target → label "belum ada target".
- Badge status data (`PUBLISHED`/`PENDING`) dan badge antrian approval.
- Gaya mengikuti report teman: KPI besar, ranking Type (merah) / Model (hijau) / Unit (kuning), unduh Excel.

## Keamanan
- HTTPS (Caddy), cookie re-auth ditandatangani, XSRF aktif, error detail disembunyikan.
- bcrypt, password minimal 10 karakter, wajib ganti saat login pertama; kunci akun 15 menit setelah 5 gagal login.
- Admin pertama via `python cli.py create-admin` di server (tanpa akun bawaan).
- PostgreSQL hanya di jaringan internal Docker; secret di `.env`; backup `pg_dump` harian 14 hari.

## Verifikasi
1. `pytest` (unit):
   - golden test: dengan minggu lama, PA/UoA Week 1–4 & total cocok dengan sheet Summary (Week 1 PA 0,65798 / UoA 0,49247); total rit 32.893, OB 778.796 BCM, ton 94.855,44 (sebelum BATAL), fuel 1.380.293 L, receipt 1.189.002 L.
   - reliability Sep: 1.489 stoppage, MTBS 20,5 jam, MTTR 23,0 jam, Scheduled Down 12,4%.
   - split site: MAS + BAU + UNMAPPED = total file; PA MAS 71,1% / BAU 54,5%.
   - target: import Target.xlsx → Sep 2026 PA = NULL ("belum ada target"), UoA 60%; import untuk site tertentu saja.
   - validasi struktur: file dengan sheet/kolom hilang ditolak.
   - akses & cache: Viewer BAU tidak menerima baris MAS/PENDING walau dataset MAS sudah ada di cache.
   - approval: auto-approve hanya jika tanpa DQ kritis; approve → versi lama SUPERSEDED; rollback berfungsi.
2. `AppTest`: navigasi per role, guard halaman admin, lockout login; link Display valid membuka layar TV site-nya saja, token dicabut/salah ditolak, Display tidak bisa membuka halaman lain.
3. Layar TV: `core/tv.py` untuk MAS Sep menghasilkan PA MTD 71,1%, UoA 51,3%, hari lengkap terakhir 22 Sep (PA 72,7%, UoA 28,1%), OB MTD 537.376 BCM, coal 59.040 t; render di browser 1920×1080 tanpa scroll; refresh otomatis memperbarui "terakhir diperbarui".
4. `docker compose up` lokal → `cli.py create-admin` → 4 user contoh + 1 perangkat Display → upload Eq.Event → import Target.xlsx → approve per site → cek tampilan tiap role, refresh browser tetap login, buka link Display di browser kiosk dan pastikan data baru muncul ±5 menit setelah approve.
5. Saat production: deploy VPS + domain, cek HTTPS & header keamanan, backup berjalan, uji di TV sungguhan di tiap site.

## Progres
- [x] Studi data `Eq.Event.xlsb`, report PDF, `Prod.Act`, `Populasi Unit.xlsx`, `Target.xlsx`
- [x] Keputusan desain & 12 poin review selesai
- [x] Riset context7 & perbaikan plan
- [x] Keputusan tampilan TV per site (Display role, 1 layar, MTD + hari lengkap terakhir, 1080p)
- [x] Setup project, Docker Compose (belum diuji, Docker belum terpasang), PostgreSQL Laragon, Alembic, config.toml
- [x] Auth: streamlit-authenticator + tabel users, lockout 5x/15 menit, idle 60 menit, role navigation, akses site, CLI create-admin/create-user/reset-password
- [x] Ingest: io + validate + clean + split site + stoppage + DQ + golden test (16 test lulus)
- [~] Target: import Target.xlsx (CLI) ✓ · halaman Target & Plan, interval PM, mapping standby (UI) belum
- [x] Upload (preview → submit), Approval (auto-approve), Riwayat Upload + rollback (26 test lulus)
- [ ] **Layar TV**: core/tv.py, halaman TV 1080p, perangkat Display & token, Preview TV
- [ ] Dashboard: Overview, PA/UA, Time Distribution, Reliability
- [ ] Dashboard: Produksi OB, Coal Getting, Loader & Fleet, Fuel, Data Quality
- [ ] Admin: Users & Roles, Sites & Mapping, Audit Log
- [ ] Uji end-to-end per role (lokal); deploy VPS saat production
