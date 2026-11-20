# HF Studio · Windows (MiniMax H3 Image + LTX-2.3 Video + MiniMax H3 Video + Krea 2 Turbo + Qwen Image 2.1 + P-H3 + Z-Image Turbo + LTX-Video Distilled + Kokoro TTS + Gemma 4 31B + LTX-2.5 + TRELLIS.2 + Wan 2.2 Fast + FLUX.3 Image Klein)

On dört Hugging Face Space'inin Gradio istekleri HAR kayıtlarından tersine mühendislikle
çıkarıldı ve tek bir Windows tkinter uygulamasında toplandı. Açılışta space listesi gelir,
hangisiyle çalışacağını sen seçersin. Her üretim proxy listesindeki tek bir IP üzerinden gider,
yeni üretimde sıradaki IP'ye geçer.

## Çalıştırma

En kolay: **`baslat.bat`** dosyasına çift tıkla → **Space seç** ekranı açılır.

Komut satırında:

```bat
cd C:\Users\ozan\Desktop\hugginface
python launcher.py                    :: space listesi (kısayol)
python apps/hf_image_app.py           :: doğrudan MiniMax görsel arayüzü
python apps/ltx_app.py                :: doğrudan LTX video arayüzü
python apps/minimax_video_app.py      :: doğrudan MiniMax H3 fotoğraftan video
python apps/krea_app.py               :: doğrudan Krea 2 Turbo görsel arayüzü
python apps/qwen_app.py               :: doğrudan Qwen Image 2.1 görsel arayüzü
python apps/ph3_app.py                :: doğrudan P-H3 görsel arayüzü
python apps/zimage_app.py             :: doğrudan Z-Image Turbo görsel arayüzü
python apps/ltx09_app.py              :: doğrudan LTX-Video Distilled arayüzü
python apps/kokoro_app.py             :: doğrudan Kokoro TTS arayüzü
python apps/gemma31b_app.py           :: doğrudan Gemma 4 31B sohbet arayüzü
python apps/ltx25_app.py              :: doğrudan LTX-2.5 video arayüzü
python apps/trellis2_app.py           :: doğrudan TRELLIS.2 görselden 3D arayüzü
python apps/wan22_app.py              :: doğrudan Wan 2.2 Fast fotoğraftan video arayüzü
python apps/flux3_app.py              :: doğrudan FLUX.3 Image Klein görsel arayüzü
python core/local_api.py              :: yerel API sunucusu (bkz. docs/AGENTS.md)
```

Gerekli paketler zaten kurulu; başka makinede: `pip install requests pillow`.

## Space listesi

| Space | Tür | Ne yapar |
|---|---|---|
| `MiniMaxAI/minimax-h3-image` | Görsel | Fotoğraf düzenleme / metinden görsel. 4-16 MP, 1-8 referans fotoğraf |
| `rdata92/LTX-2.3-10Eros` | Video | Tek fotoğraftan video (i2v). 1-10 sn, 768p-1344p, preset + negatif prompt |
| `wank3r/minimax-h3` | Video | Fotoğraftan video (i2v). 16 canvas oranı, 1-10 sn, adım, seed, upsample/turbo, opsiyonel son kare |
| `Intruzo/Krea-2-Turbo_v2` | Görsel | Metinden görsel veya görsel düzenleme (edit). 41 parametre, checkpoint, LoRA |
| `linoyts/qwen-image-2-1-realtime` | Görsel | Metinden görsel veya en fazla 10 referansla düzenleme. /prepare + /generate, oran, çözünürlük |
| `PrunaAI/P-H3-Image` | Görsel | Metinden görsel (/generate) veya kaynak + 7 referansla düzenleme (/edit). Oran, çözünürlük |
| `mrfakename/Z-Image-Turbo` | Görsel | Metinden hızlı görsel. Genişlik/yükseklik, adım, seed. |
| `Lightricks/ltx-video-distilled` | Video | Fotoğraftan video (i2v). Otomatik boyut, süre, frame, guidance. |
| `hexgrad/Kokoro-TTS` | Ses | Metinden ses. 28 ses, hız ve ZeroGPU/CPU seçimi. |
| `mxderncultxre/Gemma4-31b-uncensored-assistant` | Sohbet | Gemma 4 31B sohbet. Sistem promptu, örnekleme parametreleri, geçmiş. |
| `Lightricks/LTX-2.5` | Video | Metinden veya opsiyonel fotoğraftan sesli video. Otomatik boyut, süre, decoder, auto length, prompt geliştirme. |
| `microsoft/TRELLIS.2` | 3D | Tek görselden dokulu 3D model (GLB). Resolution, seed, decimation, texture ve 3 aşamalı gelişmiş ayarlar. |
| `zerogpu-aoti/wan2-2-fp8da-aoti-faster` | Video | 14B + Lightning LoRA ile 4-8 adımda fotoğraftan video (i2v). Steps, süre, iki guidance, seed, negatif prompt. |
| `black-forest-labs/flux-3-image-klein` | Görsel | Metinden veya en fazla 10 referans görselle üretim. Distilled (16 step) / Base (50 step), oran, çözünürlük, steps, guidance, seed. |

Liste `spaces.json` dosyasından okunur. Yeni bir space eklemek için istemci + arayüz modülünü
yazıp buraya bir kayıt eklemek yeterli (`modul` alanı `main()` içeren Python dosyası).
Uygulamalardaki **⌂ Space seç** düğmesi menüye geri döner.

## Kullanım — Görsel (MiniMax H3)

1. **+ Fotoğraf** ile 1–8 fotoğraf ekle (boş bırakırsan metinden üretir).
2. Prompt yaz; fotoğraflara `<Picture 1>`, `<Picture 2>` … diye atıf yap.
3. Oran / çözünürlük / seed ayarla, **ÜRET** (veya Ctrl+Enter).
4. Sonuç sağda görünür, `outputs\` klasörüne PNG olarak kaydedilir.

## Kullanım — Video (LTX-2.3)

1. **Seç** ile tek bir fotoğraf yükle (LTX i2v tek görüntüyle çalışır).
2. Prompt: örn. `animate this photo`. Negatif prompt hazır gelir, istersen değiştir.
3. Preset (`tuned` / `original` / `tuned #2` / `experimental #1`), mod
   (`anchor only` / `auto face` / `manual bbox`), süre (1–10 sn), çözünürlük, seed.
4. **▶ VİDEO ÜRET**. Üretim 1–5 dakika sürebilir; kuyruk sırası ve tahmini süre günlükte görünür.
5. Sonuç `outputs\ltx_<tarih>.mp4` olarak kaydedilir; **Oynat** varsayılan oynatıcıda açar.

## Kullanım — Fotoğraftan video (MiniMax H3)

1. **Seç** ile başlangıç fotoğrafını yükle. İstersen **Son kare** olarak ikinci bir fotoğraf ver
   (video o kareye doğru ilerler); boş bırakılırsa yalnızca ilk kareden üretilir.
2. Prompt: hareketi ve kamera akışını yaz (örn. *"slow cinematic push in, gentle motion"*).
3. **Canvas** (16 oran: 16:9, 9:16, 1:1, 4:3, 3:4, 21:9; `fast` / normal / `full`),
   süre (1–10 sn), adım (10–50), seed, **upsample** ve **turbo** seçenekleri.
4. **▶ VİDEO ÜRET**. Üretim genelde 1–3 dakika sürer; kuyruk sırası ve tahmini süre günlükte görünür.
5. Sonuç `outputs\minimax_video_<tarih>.mp4` olarak kaydedilir; **Oynat** varsayılan oynatıcıda açar.

Space, fotoğrafın oranına göre farklı bir canvas önerirse günlükte bunu bildirir; arayüzde
seçtiğin canvas korunur ve video tam o çözünürlükte üretilir.

## Kullanım — Görsel (Krea 2 Turbo)

1. **Mod** seç: `text2image` metinden üretir, `edit` bir görseli düzenler.
2. `edit` için **Seç** ile bir görsel yükle; istersen **2. referans** ekle.
3. Prompt yaz; `edit` modunda **Düzenleme talimatı** alanını da doldur.
4. Boyut (genişlik/yükseklik 512-2048), megapiksel (0.25-4), grounding (384-1536),
   referans gücü, adım (4-40), CFG (1-5), sampler, scheduler, seed ve checkpoint ayarla.
5. **▶ GÖRSEL ÜRET** (veya Ctrl+Enter). Sonuç sağda görünür, `outputs\krea_<tarih>.png` olarak kaydedilir.

> Bu space'in varsayılan checkpoint'i ve katalog LoRA'ları yetişkin içerikli modeller içerir.
> İstemci yalnızca API isteklerini yeniden üretir; içerik üretimi kullanıcının prompt'una bağlıdır.

## Kullanım — Görsel (Qwen Image 2.1)

1. İstersen **Ekle** ile en fazla 10 referans görsel yükle (boş bırakırsan metinden üretir).
2. Prompt yaz; **Oran** (Auto, 1:1, 4:3 … 9:16) ve **Çözünürlük** (512/1024/1536) seç.
3. Seed alanına sayı yaz veya **rastgele seed** kutusunu işaretle. İstersen **prompt'u zenginleştir** (yavaş).
4. **▶ GÖRSEL ÜRET** (veya Ctrl+Enter). Önce `/prepare` seed'i belirler, sonra `/generate` görseli üretir.
5. Sonuç `outputs\qwen_<tarih>.png` olarak kaydedilir.

## Kullanım — Görsel (P-H3)

1. **Mod**: `generate` metinden üretir, `edit` görsel düzenler.
2. `edit` için **Ekle** ile kaynak görseli (ilk sıra) ve istersen en fazla 7 referans ekle.
3. Prompt / düzenleme talimatı yaz; oran (4:3, 1:1 …), çözünürlük (8 MP vb.), seed ve upsample ayarla.
4. **▶ GÖRSEL ÜRET**. Sonuç `outputs\ph3_<tarih>.png` olarak kaydedilir.

## Kullanım — Görsel (Z-Image Turbo)

1. Prompt yaz (örn. `a cinematic portrait in soft natural light`).
2. Genişlik / yükseklik (512–2048, 64'ün katları), adım (1–20) ve seed ayarla.
3. **Rastgele seed** açıksa sunucu seed seçer; kapatırsan yazdığın seed kullanılır.
4. **▶ GÖRSEL ÜRET** (veya Ctrl+Enter). Sonuç `outputs\zimage_<tarih>.png` olarak kaydedilir.

> Bu space'te yükleme (upload) isteği yoktur; yalnızca tek `/generate_image` çağrısı vardır.

## Kullanım — Fotoğraftan video (LTX-Video Distilled)

1. **Seç** ile kaynak fotoğrafı yükle.
2. Prompt (hareket tarifi) ve negatif prompt'u düzenle.
3. Genişlik/yükseklik (256–1280), süre (0.3–8.5 sn), frame (9–257), seed,
   guidance (1–10) ve **improve texture** ayarlarını yap.
4. **▶ VİDEO ÜRET**. Önce görsel oranına göre gerçek boyutlar hesaplanır, sonra video üretilir (1–5 dk).
5. Sonuç `outputs\ltx09_<tarih>.mp4` olarak kaydedilir; **Oynat** varsayılan oynatıcıda açar.

> HAR'da görülen upload_progress SSE'si yalnızca yükleme ilerlemesidir, istemcide atlanır.

## Kullanım — Video (LTX-2.5)

1. Kaynak fotoğraf **opsiyonel**: **Seç** ile yükle, **Kaldır** ile temizle. Fotoğraf yoksa
   metinden video (t2v), varsa fotoğraftan video (i2v) üretilir.
2. Prompt yaz. **Prompt geliştir (Gemma-4)** açıkken sunucu prompt'u LTX-2.5 tarzına çevirir;
   üretilen prompt günlükte görünür.
3. Genişlik/yükseklik (512–1536), süre (1–5 sn), seed, **decoder** (`conv` hızlı / `diffusion`
   daha kaliteli) ve **auto length** (model ≤15 sn seçer) ayarlarını yap.
4. **▶ VİDEO ÜRET**. Fotoğraf varsa önce görsel oranına göre boyutlar hesaplanır, sonra video
   üretilir (1–5 dk).
5. Sonuç `outputs\ltx25_<tarih>.mp4` olarak kaydedilir; **Oynat** varsayılan oynatıcıda açar.

> HAR'da görülen `upload_progress` SSE'si yalnızca yükleme ilerlemesidir, istemcide atlanır.

## Kullanım — Görselden 3D (TRELLIS.2)

1. **Seç** ile tek bir görsel yükle. (Ön planı alpha ile maskelenmiş görseller daha iyi sonuç verir.)
2. **Resolution** (512/1024/1536), **seed** / **rastgele seed**, **decimation** (100k–500k) ve
   **texture** (1024–4096) ayarlarını yap.
3. **⚙ Gelişmiş…** ile 3 aşamanın (sparse structure / shape / material) guidance, rescale,
   sampling steps ve rescale T değerlerini düzenleyebilirsin.
4. **▶ 3D ÜRET**. Sırasıyla görsel ön işlenir, seed belirlenir, 3D model üretilir ve GLB çıkarılır
   (1–3 dk + GLB çıkarma).
5. Sonuç `outputs\trellis2_<tarih>.glb` olarak kaydedilir; **Aç** dosyayı varsayılan uygulamada
   açar (Blender / Windows 3D Viewer).

> HAR'da görülen `upload_progress` SSE'si ve walkthrough (`fn 6 /lambda`) adımı istemcide atlanır.

## Kullanım — Fotoğraftan video (Wan 2.2 Fast)

1. **Seç** ile kaynak fotoğrafı yükle.
2. Prompt (hareket tarifi) ve istersen negatif prompt yaz.
3. **Steps** (1–30, vars. 6), **Süre** (0.5–5 sn, vars. 3.5), iki **guidance** (0–10)
   ve seed / **rastgele seed** ayarlarını yap.
4. **▶ VİDEO ÜRET**. Tek `/generate_video` çağrısıyla video üretilir (30–120 sn).
5. Sonuç `outputs\wan22_<tarih>.mp4` olarak kaydedilir; **Oynat** varsayılan oynatıcıda açar.

> HAR'da görülen `upload_progress` SSE'si yalnızca yükleme ilerlemesidir, istemcide atlanır.

## Kullanım — Görsel üretimi (FLUX.3 Image Klein)

1. Prompt yaz. İstersen **Referans görseller** bölümünden en fazla 10 görsel ekle
   (metinden üretim için gerekmez).
2. **Model** (Distilled 16 step / Base 50 step), **Oran** (1:1 … 9:16) ve
   **Çözünürlük** (1K/2K/4K) seç; **↳ oran/çözünürlükten boyut** ile genişlik/yüksekliği doldur.
3. Steps (1–50), Guidance (0–10), seed / **rastgele seed** ve **prompt upsampling** ayarlarını yap.
4. **▶ GÖRSEL ÜRET**. Tek `/generate` çağrısıyla görsel üretilir (20–90 sn).
5. Sonuç `outputs\flux3_<tarih>.png` olarak kaydedilir; **Aç** varsayılan uygulamada açar.

> HAR'da görülen `describe_result` (fn 34), `boxes_toggle` (fn 32), `use_as_reference` (fn 30),
> `sync_references` (fn 25) ve `/component_server/get_app_version` istekleri yalnızca UI içindir,
> istemcide atlanır.

## Kullanım — Metinden ses (Kokoro TTS)

1. Metin yaz (~500 karakter sınırı; Generate modu).
2. **Ses** listesinden bir ses seç (28 seçenek, varsayılan `af_heart`).
3. **Hız** (0.5–2.0) ve **ZeroGPU / CPU** seçimini yap.
4. **▶ SES ÜRET**. Sonuç `outputs\kokoro_<tarih>.wav` olarak kaydedilir; **Oynat** varsayılan oynatıcıda açar.

## Kullanım — Sohbet (Gemma 4 31B)

1. Sol panelde sistem promptu ve örnekleme ayarlarını (max token, temperature,
   top-p/top-k, repetition) düzenle.
2. Sağdaki mesaj kutusuna yaz ve **Gönder** (veya Enter).
3. Konuşma geçmişi oturum boyunca korunur; her yeni mesajda space'e gönderilir.
4. **🔄 Yeni konuşma** geçmişi ve oturumu sıfırlar; **💾 Konuşmayı kaydet** JSON olarak yazar.

> HAR'da ikinci mesaj ZeroGPU kota hatası almıştır. İstemci oturum başlığı
> göndermediği için bu hata oluşursa arayüzde açıkça gösterilir.

## Seed (tüm space'ler)

- Seed alanına **elle sayı yazabilirsiniz**; yazdığınız anda **Rastgele seed** kutusu
  otomatik kapanır ve yazdığınız değer kullanılır (günlükte "Seed elle girildi" görünür).
- **🎲** düğmesi somut bir rastgele sayı üretip alana yazar; böylece sonucu sonra
  aynı seed ile tekrar üretebilirsiniz.
- Kutu işaretliyken sunucu kendi seed'ini seçer (`-1` gönderilir); üretim bitince
  gerçek seed günlükte ve sonuç bilgisinde görünür.

## Proxy

- Liste: `ips-datacenter_proxy12026-11-16T01_15_06.647Z.txt` — **kimlik bilgisi içerir, repoya
  yüklenmez** (`.gitignore`'da).
- Dosyada 23.001 satır var ama bunların 503'ü gerçek/benzersiz IP; gerisi
  `-ip-undefined` tekrarı. İstemci sadece geçerli 503 IP'yi kullanır.
- Her üretimde tek bir IP kullanılır (yükleme + join + SSE aynı proxy'den gider); yeni
  üretimde **en eski kullanılan** IP seçilir (FIFO / LRU).
- **Aynı proxy iki kez arka arkaya kullanılmaz** — son kullanılan atlanır.
- Kullanım verisi **SQLite** (`proxy_state.db`) içinde tutulur: `proxies(ip, last_used,
  use_count, bad, updated_at)` + `state(key, value)`.
- Proxy seçildiği **anda** işaretlenir ve diske yazılır; üretimin bitmesi beklenmez.
  Seçim + işaretleme tek `BEGIN IMMEDIATE` transaction'ı içinde olduğu için **aynı anda
  çalışan iki sekme aynı proxy'yi alamaz**.
- Proxy'i kapatmak için arayüzdeki **Her üretimde farklı proxy** kutusunu boşalt.
- Ölü bir proxy denk gelirse o üretim için otomatik olarak bir sonraki IP'ye geçer
  (`bad=1` olarak işaretlenir ve atlanır).
- **Sonuç dosyasının indirilmesi normalde proxy'siz yapılır**; dosya herkese açık olduğu için
  kota/rate-limit gerektirmez ve proxy trafiğini şişirmez. Üretim istekleri (yükleme dahil)
  proxy'den gider.
- Space bazen birden fazla kopya (replica) halinde çalışır; dosya yalnızca onu üreten kopyanın
  belleğinde kayıtlıdır. Yanlış kopyaya düşen indirme isteği
  `403 {"detail": "File not allowed: ..."}` alır (IP banı / token sorunu değildir).
  Bu yüzden indirme sırası: 2 doğrudan deneme → gerekirse üretim proxy'si ile 2 deneme
  (çıkış IP'si değişince istek başka kopyaya gider).
- Görsel ve video indirmelerinde bu davranış aynıdır (`RotatingTransport.download_result`).

DB içeriğini görmek için: `python scripts/db_bilgi.py` · testler: `python scripts/test_proxy_db.py`

## Proje yapısı

```
hugginface/
├─ apps/          tkinter arayüzleri (launcher + 14 space)
├─ clients/       HF API istemcileri (ortak transport/proxy katmanı hf_image_client'da)
├─ core/          altyapı: proxy_db.py, local_api.py (yerel HTTP API)
├─ config/        spaces.json + settings*.json (otomatik, git'e girmez)
├─ data/          *.har kaynakları, proxy listesi, proxy_state.* (git'e girmez)
├─ docs/          README.md, REVERSE.md, AGENTS.md, test.html (API test paneli)
├─ scripts/       db_bilgi.py, test_proxy_db.py, test_proxy.py
├─ outputs/       üretilen PNG / MP4 (git'e girmez)
├─ paths.py       ortak yol tanımları
├─ launcher.py    kısayol → apps/launcher.py
├─ local_api.py   kısayol → core/local_api.py
├─ baslat.bat     çift tıkla: space listesi
└─ api_baslat.bat çift tıkla: yerel API (http://127.0.0.1:8787)
```

| Klasör / dosya | Görev |
|---|---|
| `apps/launcher.py` | Açılışta space seçim ekranı (ızgara kartlar, tek tık) |
| `apps/*_app.py` | On dört space'in tkinter arayüzü |
| `clients/hf_image_client.py` | Ortak transport / ProxyPool / RotatingTransport + MiniMax H3 Image |
| `clients/*_client.py` | LTX, MiniMax Video, Krea, Qwen, P-H3, Z-Image, LTX-Distilled, LTX-2.5, TRELLIS.2, Kokoro, Gemma, Wan 2.2, FLUX.3 istemcileri |
| `core/proxy_db.py` | SQLite proxy kullanım deposu (`ProxyDB`, FIFO/LRU) |
| `core/local_api.py` | Yerel FastAPI sunucusu — agent'lar için (bkz. `docs/AGENTS.md`) |
| `config/spaces.json` | Space kayıtları (ad, host, modül, açıklama) |
| `config/settings*.json` | Son kullanılan ayarlar (otomatik, git'e girmez) |
| `data/*.har` | Kaynak HAR kayıtları (git'e girmez) |
| `data/ips-*proxy*.txt` | Proxy listesi — kimlik bilgisi içerir, ASLA commit etme |
| `data/proxy_state.*` | Proxy kullanım durumu (otomatik, git'e girmez) |

## Teknik özet — MiniMax H3 (`huggingface.co.m3max.har`)

1. `POST /gradio_api/queue/join` `fn_index: 1` → `{state, seed, randomize, effort}`
2. `GET /gradio_api/queue/data?session_hash=...` → `process_completed`
3. `POST /gradio_api/queue/join` `fn_index: 2` → `[null]` (plan sunucu state'inde)
4. `GET /gradio_api/queue/data?session_hash=...` → `process_completed`
5. Sonuç URL'sinden PNG indir (`/gradio_api/file=...`)

`state` içindeki fotoğraflar tarayıcıdaki gibi `data:image/jpeg;base64,...` olarak gider;
ayrı bir upload isteği yoktur.

## Teknik özet — LTX-2.3 (`huggingface.co.ltx23.har`)

Host: `https://rdata92-ltx-2-3-10eros.hf.space`

1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files`
   → `["/tmp/gradio/<hash>/<ad>.jpg"]`
2. `POST /gradio_api/queue/join?__theme=system` — `fn_index: 0`, 88 elemanlı `data`
   (`/generate`), `trigger_id: 145`, `session_hash` → `{"event_id": "..."}`
3. `GET /gradio_api/queue/data?session_hash=...` → `process_completed`
   (`output.data[0]` = video FileData, `data[1]` = durum metni, `data[2]` = kullanılan seed)
4. `GET /gradio_api/file=/tmp/gradio/<hash>/output.mp4` → MP4

`data` dizisinin 88 elemanı: `image_path, prompt, negative_prompt, preset, seconds,
max_width, max_height, mode, face_bbox, likeness_strength, ..., seed, randomize_seed, ...`
(bkz. `ltx_video_client.PARAMS`). Tarayıcı `snap_multiple`/`msr_frame_count` için sayısal
değer gönderiyor; istemci de öyle gönderir.

Oyuncu tarafında `x-zerogpu-uuid` / `x-zerogpu-token`, cookie, `Authorization` veya HF
tokeni gönderilmez. ZeroGPU oturum başlıkları bilinçli olarak eklenmez (bkz. `REVERSE.md`).

## Teknik özet — MiniMax H3 Video (`huggingface.co.minimax.img2vid.har`)

Host: `https://wank3r-minimax-h3.hf.space`

1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files`
   → `["/tmp/gradio/<hash>/<ad>.png"]`
2. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 0` (`/_fit_keyframe`),
   `data: [<FileData>, "<canvas>"]`, `trigger_id: 24` → `{"event_id": "..."}`
3. `GET /gradio_api/queue/data?session_hash=...` → `process_completed`
   (`output.data[0]` = canvas'a sığdırılmış ilk kare; Gradio `{"__type__": "update"}`
   sarmalayıcısı açılır)
4. `POST /gradio_api/queue/join` — `fn_index: 1` (`/generate`), `trigger_id: 26`,
   13 elemanlı `data`:
   `prompt, image_path, last_image_path, canvas, duration, steps, seed, upsample, turbo,
   nsfw_lora_keys, custom_lora_url, custom_lora_scale, custom_lora_trigger`
5. `GET /gradio_api/queue/data?session_hash=...` → `process_completed`
   (`output.data[0]` = video FileData; video + ses track'i birlikte gelir)
6. `GET /gradio_api/file=/tmp/gradio/<hash>/h3-*.mp4` → MP4

Canvas seçenekleri `/gradio_api/info` şemasından alınmıştır (16 adet; `fast` = hızlı,
`full` = tam çözünürlük). `duration` saniye, `steps` örnekleme adımı, `seed: -1` sunucunun
rastgele seçmesi anlamına gelir. ZeroGPU oturum başlıkları ve cookie / `Authorization` /
HF tokeni kullanılmaz (bkz. `REVERSE.md`).

## Teknik özet — Krea 2 Turbo (`huggingface.co.krea.imgedit.har`)

Host: `https://intruzo-krea-2-turbo-v2.hf.space` · Gradio 5.44.1 (SvelteKit arayüzü)

1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files`
   → `["/tmp/gradio/<hash>/<ad>.jpg"]`
2. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 4` (`/_generate_wrapper`),
   `trigger_id: 79`, `session_hash`, **41 elemanlı** `data` dizisi → `{"event_id": "..."}`
3. `GET /gradio_api/queue/data?session_hash=...` → `process_completed`
   (`output.data[0]` = gallery/görsel, `data[1]` = durum, `data[2]` = kullanılan seed)
4. `GET /gradio_api/file=/tmp/gradio/<hash>/output_0.png` → PNG

**Parametrelerin gönderilme biçimi (bu space'in ayırt edici yanı):**

- 41 parametrenin **hiçbiri atlanmaz**; tarayıcı varsayılan değerleri de açıkça gönderir
  (`1024`, `1.4`, `768`, `0.0` …). İstemci de tüm slotları doldurur.
- Sıra `/gradio_api/info` → `/_generate_wrapper` ve `/config` dosyasındaki `inputs`
  listesinden doğrulandı: `mode, prompt, edit instruction, primary image, second reference,
  width, height, target megapixels, grounding resolution, ref strength 1/2, steps, CFG,
  sampler, scheduler, seed, randomize seed, GPU budget, base checkpoint, custom repo/filename/
  revision, LoRA dataframe` + **18 katalog LoRA slider'ı** (hepsi `0.0`).
- Görsel slot'u yükleme yanıtından üretilen bir **FileData** sözlüğüdür:
  `path` + `url` (`BASE_URL + "/gradio_api/file=" + path`) + `orig_name` + `size` +
  `mime_type` + `meta`. Tarayıcı URL'deki boşluğu kodlamadan gönderir; `requests` kodlar.
- `trigger_id: 79` ve `fn_index: 4`, space'in `/config` dosyasındaki generate düğmesi
  click event'inden gelir; `session_hash` 10 karakterli rastgele değerdir.
- Tarayıcı ilk olarak `fn_index: 0` (`data: ["edit"]`, `/on_mode_change`) isteği gönderir;
  bu yalnızca arayüz görünürlüğünü değiştirir, üretimi etkilemez ve istemcide atlanır.
- HAR'ın 2 join isteğinde `x-zerogpu-uuid` / `x-zerogpu-token` görünür; bunlar tarayıcının
  ZeroGPU oturum kimliğidir ve istemcide **bilinçli olarak gönderilmez** (bkz. `REVERSE.md`).
- HAR'da cookie / `Authorization` / HF tokeni yoktur; istemci de göndermez.

## Teknik özet — Qwen Image 2.1 (`huggingface.co.qwen21.imgedit.har`)

Host: `https://linoyts-qwen-image-2-1-realtime.hf.space` · Gradio 6.30.0 (SvelteKit)

1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files` (her görsel ayrı)
   → `["/tmp/gradio/<hash>/<dosya>"]`
2. `POST /gradio_api/queue/join` — `fn_index: 10` (`/prepare`), `trigger_id: 12`,
   6 elemanlı `data`: `[prompt, gallery, enhance, seed, randomize_seed, aspect_ratio]`
   → SSE `output.data = [prompt, rewritten, seed, aspect_ratio]`
3. `POST /gradio_api/queue/join` — `fn_index: 11` (`/generate`), `trigger_id: 12`,
   5 elemanlı `data`: `[prompt, gallery, seed, resolution, aspect_ratio]`
   → SSE `output.data[0]` = sonuç görseli
4. `GET /gradio_api/file=/tmp/gradio/<hash>/image.png` → PNG

**Parametre notları:**

- `gallery` düz FileData değil, Gradio Gallery öğeleridir:
  `[{"image": {path, url, orig_name, size, mime_type, meta}, "caption": null}, …]` (en fazla 10).
- `/prepare` çıktısındaki **seed ve oran** `/generate` çağrısında kullanılır; `randomize_seed:
  true` ise sunucu seed üretir ve döndürür. Prompt (enhance açıksa yeniden yazılmış hali) de
  generate'e gider.
- HAR'da prompt harf harf yazıldığı için `fn_index: 5` (`/push_live`) 20+ kez çağrılmış;
  bunlar yalnızca 512px "realtime" önizleme içindir (`outputs: []`), üretimi etkilemez ve
  istemcide atlanır.
- HAR'ın join isteklerinde `x-zerogpu-*` görünür; **gönderilmez** (bkz. `REVERSE.md`).

## Teknik özet — P-H3 Image (`huggingface.co.ph3.imgedit.har`)

Host: `https://prunaai-p-h3-image.hf.space` · Gradio 6.30.0

1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files` → `/tmp/gradio/<hash>/<dosya>`
2. `POST /gradio_api/queue/join?__theme=dark` — `trigger_id: null`:
   - `fn_index: 0` (`/generate`), 6 eleman: `[prompt, aspect, resolution, upsample, seed, randomize]`
   - `fn_index: 1` (`/edit`), 13 eleman: `[source, instruction, ref2..ref8, resolution, upsample, seed, randomize]`
3. `GET /gradio_api/queue/data?session_hash=...` → `process_completed`,
   `output.data[0] = {"image_data": "data:image/jpeg;base64,..."}` — görsel **SSE içinde gömülü** gelir,
   ayrıca bir `GET /gradio_api/file=...` isteği **yapılmaz**; base64 çözülür. (FileData/path yolu da desteklenir.)

**Parametre notları:**

- Bu space'te görseller FileData sarmalayıcısı değil, **doğrudan `/tmp/gradio/...` path string'i** olarak gider
  (component tipi "Api"/string). HAR'daki gerçek veri: `["/tmp/gradio/.../d.jpg", "angry", null × 7, "8 MP", true, 42, true]`.
- HAR'da 12 `/workflow/gradio_api/component_server` isteği (`curated_modalities`, `list_bound_fns`,
  `get_token` vb.) ve 1 workflow canvas join'i (`fn 0`, `data=[]`) vardır; UI/meta içindir, atlanır.
- Join isteklerinde `x-zerogpu-*` ve `x-gradio-user` görünür; **gönderilmez** (bkz. `REVERSE.md`).

## Teknik özet — Z-Image Turbo (`huggingface.co.z.image.har`)

Host: `https://mrfakename-z-image-turbo.hf.space` · Gradio 6.20.0

1. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 3` (`/generate_image`),
   `trigger_id: 16`, 6 elemanlı `data` → `{"event_id": "..."}`:
   `[prompt, height, width, num_inference_steps, seed, randomize_seed]`
2. `GET /gradio_api/queue/data?session_hash=...` — SSE; `process_completed` beklenir
   (`output.data[0]` = görsel FileData, `data[1]` = kullanılan seed).
3. `GET /gradio_api/file=/tmp/gradio/<hash>/image.png` → PNG.

**Parametre notları:**

- Sıra `/gradio_api/info` ve `/config` `inputs` listesi
  (`[4, 7, 8, 10, 13, 12]` = prompt, height, width, steps, seed, randomize)
  ile doğrulandı; HAR'daki gerçek dizi `["sample prompt", 1024, 1024, 9, 42, true]`.
- Varsayılanlar: height/width 1024 (512–2048, adım 64), steps 9 (1–20), seed 42,
  randomize_seed true. İstemci tüm slotları açıkça gönderir.
- HAR'da ayrıca `fn_index: 2` (`_start_timer`, `data: []`) ve `fn_index: 4`
  (`_show_took`, `data: [null]`) join'leri vardır; ikisi de yalnızca süre göstergesini
  günceller, üretimi etkilemez ve istemcide **atlanır**.
- Upload isteği yoktur. `x-zerogpu-*` / `x-zerogpu-token` / `x-mfn-sid` /
  `x-gradio-user` başlıkları HAR'da görünür; **gönderilmez** (bkz. `REVERSE.md`).
- Cookie / `Authorization` / HF tokeni yoktur ve gönderilmez.

## Teknik özet — LTX-Video Distilled (`huggingface.co.ltx.0.9.video.har`)

Host: `https://lightricks-ltx-video-distilled.hf.space` · Gradio 5.42.0

1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files`
   → `["/tmp/gradio/<hash>/beat_2.png"]`
2. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 0`
   (`/handle_image_upload_for_dims`), `trigger_id: 8`, 3 eleman:
   `[FileData, current_h, current_w]` → SSE `output.data = [height, width]`
3. `POST /gradio_api/queue/join` — `fn_index: 5` (`/image_to_video`),
   `trigger_id: 10`, 13 eleman:
   `[prompt, negative_prompt, image, null, height, width, mode, duration,
   frames, seed, randomize_seed, guidance, improve_texture]` → SSE `process_completed`
4. `GET /gradio_api/file=/tmp/gradio/<hash>/output_*.mp4` → MP4

**Parametre notları:**

- fn 0 çıktısı kritiktir: HAR'da `512, 704` gönderilmiş, sunucu görsel oranına göre
  `768, 1280` döndürmüş ve bu değerler fn 5'e geçmiştir. İstemci aynı zinciri izler.
- 13 parametrenin sırası `/gradio_api/info` ve `/config` `inputs` listesi
  (`[9,35,8,7,44,45,34,27,22,37,38,41,28]`) ile doğrulandı.
- Aralıklar: height/width 256–1280, duration 0.3–8.5 sn, frame 9–257,
  guidance 1–10; varsayılanlar 512/704, 2 sn, 9 frame, seed 42, randomize true.
- `mode` sabit: `image-to-video` (text/video-to-video modları bu HAR'da kullanılmadı).
- `GET /gradio_api/upload_progress` yalnızca yükleme ilerlemesi içindir, atlanır.
- Join isteklerinde `x-zerogpu-*` görünür; **gönderilmez** (bkz. `REVERSE.md`).

## Teknik özet — LTX-2.5 (`huggingface.co.ltx2.5.har`)

Host: `https://lightricks-ltx-2-5.hf.space` · Gradio 6.13.0

1. (opsiyonel görsel) `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files`
   → `["/tmp/gradio/<hash>/krea_....png"]`
2. `POST /gradio_api/queue/join?__theme=system` — `fn_index: 0`
   (`/set_dims_from_image`), `trigger_id: 4`, 1 eleman: `[FileData]`
   → SSE `output.data = [height, width]`
3. `POST /gradio_api/queue/join?__theme=system` — `fn_index: 2` (`/run`),
   `trigger_id: 22`, 10 eleman:
   `[prompt, image, height, width, duration_s, seed, decoder, auto_len,
   randomize_seed, do_enhance]` → SSE `process_completed`
   `output.data = [video FileData, prompt_sent, seed_used, length]`
4. `GET /gradio_api/file=/tmp/gradio/<hash>/tmp*.mp4` → MP4

**Parametre notları:**

- 10 parametrenin sırası `/gradio_api/info` ve `/config` `inputs`
  (`[5,4,9,8,11,16,14,12,17,19]`) ile doğrulandı.
- Görsel opsiyoneldir (`Input image (optional → image-to-video)`); verilmezse fn 0 atlanır ve
  doğrudan metinden video üretilir.
- Aralıklar: height/width 512–1536 (64 adım), duration 1–5 sn (0.5 adım), seed 0–2147483647;
  varsayılanlar 832×1472, 2 sn, seed 42, decoder `conv`, randomize true, enhance true.
- `auto_len` açıkken sunucu süreyi prompt'tan seçer (≤15 sn) ve slider'ı geçersiz kılar.
- Video çıktısı seslidir; HAR'da `video/mp4` olarak indirilmiştir.
- Join gövdesinde `event_data` yoktur; `data` + `fn_index` + `trigger_id` + `session_hash` gider.
- `GET /gradio_api/upload_progress` yalnızca yükleme ilerlemesi içindir, atlanır.
- Join isteklerinde `x-zerogpu-*` görünür; **gönderilmez** (bkz. `REVERSE.md`).

## Teknik özet — TRELLIS.2 (`huggingface.co.trellis2.har`)

Host: `https://microsoft-trellis-2.hf.space` · Gradio 6.1.0

0. `POST /queue/join` — `fn_index: 2` (`/start_session`), `data: []`
1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files`
   → `["/tmp/gradio/<hash>/qwen_....png"]`
2. `POST /queue/join` — `fn_index: 4` (`/preprocess_image`), `trigger_id: 4`,
   `data: [FileData]` → SSE `image.png` (ön işlenmiş FileData)
3. `POST /queue/join` — `fn_index: 5` (`/get_seed`), `trigger_id: 10`,
   `data: [randomize_seed, seed]` → SSE `[kullanılan_seed]`
4. `POST /queue/join` — `fn_index: 7` (`/image_to_3d`), `trigger_id: 10`, 15 eleman:
   `[image, seed, resolution, ss_guidance_strength, ss_guidance_rescale,
   ss_sampling_steps, ss_rescale_t, shape_slat_* (4), tex_slat_* (4)]`
   → SSE `[state, html önizleme]`
5. `POST /queue/join` — `fn_index: 9` (`/extract_glb`), `trigger_id: 38`,
   `data: [null, decimation_target, texture_size]` → SSE `[Model3D, DownloadButton]`
   (ilk `null`, `gr.State` input 45 için yer tutucudur; gerçek latent sözlüğü
   istemciye gönderilmez, sunucu `session_hash` ile saklar)
6. `GET /gradio_api/file=/tmp/gradio/<hash>/*.glb` → GLB

**Parametre notları:**

- 15 parametrenin sırası `/gradio_api/info` ve `/config` `inputs`
  (`[4,6,5,14,15,16,17,21,22,23,24,28,29,30,31]`) ile doğrulandı.
- `trigger_id`, olayı başlatan bileşenin id'sidir (Image 4, Generate 10, Extract GLB 38);
  Gradio JS'te `.then` zinciri bu değeri devralır. `start_session` için `null`.
- State bileşeni 45 (`image_to_3d` çıktısı) istemciye gönderilmez; `extract_glb` aynı
  `session_hash` ile çalıştığı için sunucu state'i kendisi kullanır. Doğrulandı:
  aynı `session_hash` korunduğunda proxy değişse bile state bulunuyor.
- Resolution 512/1024/1536 (varsayılan 1024); decimation 100k–500k (adım 10k);
  texture 1024–4096 (adım 1024); seed 0–2147483647, varsayılan 0 + randomize true.
- 3 aşama varsayılanları: S1 `7.5 / 0.7 / 12 / 5.0`, S2 `7.5 / 0.5 / 12 / 3.0`,
  S3 `1.0 / 0.0 / 12 / 3.0` (guidance / rescale / steps / rescale T).
- `fn 6 /lambda` yalnızca walkthrough adımıdır; üretime etkisi yoktur, atlanır.
- `GET /gradio_api/upload_progress` yalnızca yükleme ilerlemesi içindir, atlanır.
- Her üretim iki ZeroGPU çağrısı kullanır (`image_to_3d` + `extract_glb`, 120 sn).
  Anonim kota IP başına sınırlıdır; istemci `ZeroGPU quota` hatasında proxy'yi
  değiştirip otomatik tekrar dener (state `session_hash` ile korunur).
- `x-zerogpu-uuid` / `x-zerogpu-token` başlıkları yalnızca HAR kaydında görünür;
  istemci bunları, cookie'leri ve `Authorization`'ı **göndermez** (bkz. `REVERSE.md`).

## Teknik özet — Wan 2.2 Fast (`huggingface.co.wan22.aoti.fast..har`)

Host: `https://zerogpu-aoti-wan2-2-fp8da-aoti-faster.hf.space` · Gradio 6.1.0
Space: `zerogpu-aoti/wan2-2-fp8da-aoti-faster`

0. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı `files`
   → `["/tmp/gradio/<hash>/qwen_....png"]`
1. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 0` (`/generate_video`),
   `trigger_id: 16` (Generate butonu, id 16), 9 elemanlı `data` → `{"event_id": "..."}`:
   `[image, prompt, steps, negative_prompt, duration_seconds, guidance_scale,
   guidance_scale_2, seed, randomize_seed]`
2. `GET /gradio_api/queue/data?session_hash=...` — SSE; `process_completed`
   (`output.data[0]` = video FileData, `data[1]` = kullanılan seed)
3. `GET /gradio_api/file=/tmp/gradio/<hash>/tmp*.mp4` → MP4 (ranged isteklerle indirilir)

**Parametre notları:**

- 9 parametrenin sırası `/config` `inputs [5, 6, 12, 9, 7, 13, 14, 10, 11]` ve
  `/gradio_api/info` (`named_endpoints./generate_video.parameters`) ile doğrulandı.
- Return şeması: `[Video ("Generated Video"), Slider ("Seed")]`.
- HAR'daki gerçek dizi, negatif prompt dışında varsayılan değerleri kullanır; prompt
  İngilizcedir, negatif prompt Çincedir (space'in varsayılanı korunur).
- Steps 1–30 (vars. 6), duration 0.5–5 sn (vars. 3.5), guidance 0–10 (vars. 1),
  seed 0–2147483647 (vars. 42) + randomize `true`.
- `trigger_id`, olayı başlatan Generate bileşeninin id'sidir (16). Join gövdesinde
  `event_data` alanı yoktur.
- `GET /gradio_api/upload_progress` yalnızca yükleme ilerlemesidir, atlanır.
- `x-zerogpu-*` / cookie / `Authorization` başlıkları yalnızca HAR kaydında görünür;
  istemci bunları **göndermez** (bkz. `REVERSE.md`).

## Teknik özet — FLUX.3 Image Klein (`huggingface.co.flux3.klein.har`)

Host: `https://black-forest-labs-flux-3-image-klein.hf.space` · Gradio 6.30.0
Space: `black-forest-labs/flux-3-image-klein`

0. (Referans görsel varsa) `POST /gradio_api/upload?upload_id=<id>` — multipart, alan `files`
   → `["/tmp/gradio/<hash>/<ad>"]` → gallery öğeleri `[{"image": FileData, "caption": null}]`
1. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 33` (`/generate`),
   `trigger_id: 31` (Generate butonu), 10 elemanlı `data` → `{"event_id": "..."}`:
   `[prompt, gallery, mode, seed, randomize_seed, width, height,
   num_inference_steps, guidance_scale, prompt_upsampling]`
2. `GET /gradio_api/queue/data?session_hash=...` — SSE; `process_completed`
   (`output.data = [Image(FileData), seed, prompt_the_model_saw]`)
3. `GET /gradio_api/file=/tmp/gradio/<hash>/image.png` → PNG

**Parametre notları:**

- HAR'da `/config` ve `/info` yoktu; şema space'in canlı `/gradio_api/info` (`/generate`)
  ve `/config` endpoint'lerinden okundu. `inputs [23,27,28,35,36,39,40,43,44,33]`,
  `outputs [50,35,57]`, `trigger_id 31` birebir eşleşiyor.
- HAR'daki gerçek dizi: `[prompt, [], "Distilled (16 steps)", 0, true, 2048, 2048, 16, 1, true]`.
- Model: `Distilled (16 steps)` veya `Base (50 steps)`; oran 1:1/4:3/3:4/3:2/2:3/16:9/9:16;
  çözünürlük 1K/2K/4K → space tarafında width/height'e çevrilir (1K=1024, 2K=2048, 4K=4096).
- Width/height 256–4096 (adım 16), steps 1–50, guidance 0–10, seed 0–2147483647 + randomize.
- Referans galerisi en fazla 10 görsel; öğe biçimi `{"image": FileData, "caption": null}`.
- Atlanan UI-only çağrılar: fn 34 `/describe_result` (`[seed, mode, width, height]`),
  fn 32 `/boxes_toggle`, fn 30 `/use_as_reference`, fn 25 `/sync_references`,
  fn 27/28 `/set_aspect`, fn 29 `/update_steps_from_mode` ve
  `POST /gradio_api/component_server` (`get_app_version`).
- `x-zerogpu-*` / cookie / `Authorization` yalnızca HAR kaydında görünür; istemci **göndermez**.

## Teknik özet — Kokoro TTS (`huggingface.co.kokoro.tts.fast.har`)

Host: `https://hexgrad-kokoro-tts.hf.space` · Gradio 5.24.0

1. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 4` (`/Generate`),
   `trigger_id: 2`, 4 elemanlı `data` → `{"event_id": "..."}`:
   `[text, voice, speed, hardware]`
2. `GET /gradio_api/queue/data?session_hash=...` — SSE; `process_completed`
   (`output.data[0]` = ses FileData, `data[1]` = kullanılan token'lar)
3. `GET /gradio_api/file=/tmp/gradio/<hash>/audio.wav` → WAV

**Parametre notları:**

- HAR'daki gerçek dizi: `["In my younger and more vulnerable years…", "af_heart", 1, true]`.
- Şema `/gradio_api/info` içinde **yok** (endpoint'ler gizli); `/config` component'lerinden
  çıkarıldı: `inputs [22(text), 24(voice), 27(speed), 25(hardware)]`.
- 28 ses değeri (`af_heart`, `af_bella`, …, `bm_daniel`); varsayılan `af_heart`.
- Speed 0.5–2.0 (adım 0.1); hardware `true` = ZeroGPU, `false` = CPU.
- Text alanı üst sınırı ~500 karakter (Stream modu 5000, bu HAR'da kullanılmadı).
- Upload isteği yoktur. `x-zerogpu-*` / cookie / `Authorization` gönderilmez.

## Teknik özet — Gemma 4 31B (`huggingface.co.gemma31b.fast.har`)

Host: `https://mxderncultxre-gemma4-31b-uncensored-assistant.hf.space` · Gradio 6.16.0

1. `POST /gradio_api/queue/join?__theme=dark` — `fn_index: 0` (`/chat`),
   11 elemanlı `data` → `{"event_id": "..."}`:
   `[text, files, history, thinking, max_new_tokens, image_token_budget,
   system_prompt, temperature, top_p, top_k, repetition_penalty]`
2. `GET /gradio_api/queue/data?session_hash=...` — SSE; `process_completed`
   (`output.data[0] = {"reasoning": ..., "content": ..., "error": ...}`)

**Parametre notları:**

- HAR'daki ilk dizi: `["merhaba", [], [], false, 1040, 560, "<system>", 0.7, 0.9, 40, 1]`.
- İkinci join aynı `session_hash` ile geçmişi gönderir:
  `[{"role":"user","text":"merhaba","files":[]}, {"role":"assistant","text":"…","files":[]}]`.
- `/info` 11 parametreyi ve varsayılanları verir; `/config` `inputs`
  `[1..11] → output [12]` eşleşmesini doğrular.
- **Join gövdesinde `event_data` veya `trigger_id` alanı yoktur** (bu space'in
  Gradio 6.16 sürümüne özgüdür); istemci gövdeyi tam olarak bu biçimde üretir.
- Dosya indirme isteği yoktur; cevap SSE içindedir. `x-zerogpu-*` / `x-gradio-user`
  görünür ama **gönderilmez** (bkz. `REVERSE.md`).
