# HF Studio · Windows (MiniMax H3 Image + LTX-2.3 Video + MiniMax H3 Video)

Üç Hugging Face Space'inin Gradio istekleri HAR kayıtlarından tersine mühendislikle
çıkarıldı ve tek bir Windows tkinter uygulamasında toplandı. Açılışta space listesi gelir,
hangisiyle çalışacağını sen seçersin. Her üretim proxy listesindeki tek bir IP üzerinden gider,
yeni üretimde sıradaki IP'ye geçer.

## Çalıştırma

En kolay: **`baslat.bat`** dosyasına çift tıkla → **Space seç** ekranı açılır.

Komut satırında:

```bat
cd C:\Users\ozan\Desktop\hugginface
python launcher.py            :: space listesi
python hf_image_app.py        :: doğrudan MiniMax görsel arayüzü
python ltx_app.py             :: doğrudan LTX video arayüzü
python minimax_video_app.py   :: doğrudan MiniMax H3 fotoğraftan video arayüzü
```

Gerekli paketler zaten kurulu; başka makinede: `pip install requests pillow`.

## Space listesi

| Space | Tür | Ne yapar |
|---|---|---|
| `MiniMaxAI/minimax-h3-image` | Görsel | Fotoğraf düzenleme / metinden görsel. 4-16 MP, 1-8 referans fotoğraf |
| `rdata92/LTX-2.3-10Eros` | Video | Tek fotoğraftan video (i2v). 1-10 sn, 768p-1344p, preset + negatif prompt |
| `wank3r/minimax-h3` | Video | Fotoğraftan video (i2v). 16 canvas oranı, 1-10 sn, adım, seed, upsample/turbo, opsiyonel son kare |

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

DB içeriğini görmek için: `python db_bilgi.py` · testler: `python test_proxy_db.py`

## Dosyalar

| Dosya | Görev |
|---|---|
| `launcher.py` | Açılışta space seçim ekranı |
| `spaces.json` | Space kayıtları (ad, host, modül, açıklama) |
| `hf_image_app.py` | MiniMax H3 görsel arayüzü |
| `hf_image_client.py` | MiniMax H3 API istemcisi + ortak transport/proxy katmanı |
| `ltx_app.py` | LTX-2.3 video arayüzü |
| `ltx_video_client.py` | LTX-2.3 API istemcisi (upload + 88 parametreli /generate) |
| `minimax_video_app.py` | MiniMax H3 fotoğraftan video arayüzü |
| `minimax_video_client.py` | MiniMax H3 API istemcisi (upload + /_fit_keyframe + 13 parametreli /generate) |
| `proxy_db.py` | SQLite proxy kullanım deposu (`ProxyDB`) |
| `db_bilgi.py` | `proxy_state.db` içeriğini gösterir |
| `test_proxy_db.py` | Proxy havuzu testleri (FIFO, çoklu-sekme, migration) |
| `baslat.bat` | Çift tıkla: space listesini açar |
| `outputs/` | Üretilen PNG / MP4 dosyaları (git'e girmez) |
| `settings*.json` | Son kullanılan ayarlar (otomatik, git'e girmez) |
| `proxy_state.db` | Proxy kullanım veritabanı (otomatik, git'e girmez) |
| `*.har` | Kaynak kayıtlar (git'e girmez) |

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

Oyuncu tarafında `x-zerogpu-uuid`, cookie, `Authorization` veya HF tokeni gönderilmez
(HAR'da da yoktu; `x-zerogpu-uuid` yalnızca opsiyonel olarak desteklenir).

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
rastgele seçmesi anlamına gelir. `x-zerogpu-uuid` yalnızca join isteklerinde gönderilir ve
istemcide opsiyoneldir; cookie / `Authorization` / HF tokeni hiç kullanılmaz.
