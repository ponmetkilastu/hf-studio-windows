# Hugging Face Space Reverse Mühendisliği — Proje Kuralları ve Yöntemi

Bu dosya, bu depoda yeni bir Hugging Face Space'i HAR kaydından tersine mühendislikle
ekleyecek herkes (insan veya AI ajanı) için **zorunlu** kuralları ve izlenmesi gereken
yöntemi tanımlar. Amaç: aynı hataların tekrar tekrar yapılmasını önlemek.

---

## 1. ZORUNLU KURALLAR — Önce bunları oku

### 1.1. `x-zerogpu-uuid` ve `x-zerogpu-token` ASLA eklenmez

**Bu konuda tartışma yok.** Yeni bir istemci yazarken veya mevcut birini düzenlerken:

- Hiçbir isteğe `x-zerogpu-uuid` başlığı ekleme.
- Hiçbir isteğe `x-zerogpu-token` başlığı ekleme.
- Bu başlıklar için constructor parametresi, CLI argümanı, ayar dosyası alanı veya
  "opsiyonel" bir kod yolu **oluşturma**.
- HAR'da bu başlıkları görsen bile ekleme. "Tarayıcı gönderiyorsa biz de gönderelim"
  diye düşünme — **yanlıştır**.

**Neden?** Bu başlıklar HF'in tarayıcı tarafındaki ZeroGPU oturum kimliğidir
(`api.hf.space/v1/zero-gpu/sse` kanalından üretilir, süreli ve oturuma özgüdür).
Bizim istemcilerimiz kimlik doğrulamasız, anonim Gradio API çağrıları yapar.
Bu başlıklar API için gerekli değildir ve gönderilmeleri gürültü, olası hata ve
bakım yükünden başka bir işe yaramaz. Bu depodaki mevcut istemcilerin tamamı
bu başlıklar olmadan çalışır; kural budur.

> Geçmişte AI ajanları HAR'da gördükleri için bu başlıkları tekrar tekrar eklediler.
> Bunu yapma. HAR bir **gözlemdir**, kopyalanacak bir şablondur denmez — aşağıdaki
> filtreleme kuralına bak.

### 1.2. Kimlik doğrulama bilgisi gönderilmez

- `Authorization`, `Cookie`, HF token, `x-hf-token`, `x-api-key` vb. **asla** eklenmez.
- Proxy kullanıcı/parolası yalnızca proxy'e aittir, space'e değil.

### 1.3. HAR gözlemini olduğu gibi kopyalamak yerine filtrele

HAR, tarayıcının yaptığı **her şeyi** kaydeder; bunun büyük kısmı arayüz içindir,
API için değil. Bir isteği istemciye aktarmadan önce şu soruları sor:

1. Bu istek üretimi doğrudan etkiliyor mu? (upload / join / SSE / indirme = evet;
   `/config`, `/info`, `/jwt`, `/metrics`, `/events`, WAF telemetry, Stripe = hayır)
2. Bu başlık sunucu davranışını değiştiriyor mu, yoksa tarayıcı oturumuna mı ait?
   (`x-zerogpu-*`, WAF/Stripe/Cookie = oturuma ait → atmalı)
3. Bu alan sabit bir UI state'i mi? (ör. "modu edit'e geç" join'i yalnızca
   görünürlük değiştirir → atlanabilir)

**Kural: üretim zinciri dışındaki hiçbir istek/başlık istemciye taşınmaz.**

---

## 2. Genel reverse mühendislik yöntemi

### 2.1. HAR'ı ayrıştır

HAR bir JSON dosyasıdır. Python ile doğrudan okunabilir (REA MCP aracı yoksa sorun değil):

```python
import json
har = json.load(open("space.har", encoding="utf-8"))
entries = har["log"]["entries"]
```

Önce envanter çıkar:
- kaç istek var, hangi host'lar, hangi method + path grupları?
- `huggingface.co`, WAF, Stripe, CDN isteklerini **görmezden gel**.
- Hedef `*.hf.space` host'una giden istekleri filtrele.

### 2.2. Üretim zincirini bul

Tipik Gradio akışı (mevcut 4 space'in tamamında aynı iskelet):

1. `POST /gradio_api/upload?upload_id=<id>` — multipart, alan adı genelde `files`
   → `["/tmp/gradio/<hash>/<dosya>"]`
2. `POST /gradio_api/queue/join?__theme=<...>` — gövde:
   `{"data": [...], "fn_index": N, "trigger_id": M, "session_hash": "..."}`
   → `{"event_id": "..."}`
3. `GET /gradio_api/queue/data?session_hash=...` — SSE; `process_completed`
   mesajı gelene kadar oku.
4. `GET /gradio_api/file=...` — sonuç dosyasını indir (proxy'siz, 403'te proxy yedeği).

Bazı space'lerde zincir birden fazla join içerir (ör. MiniMax image'da 2 join:
plan + render; MiniMax video'da `_fit_keyframe` + `generate`). Her join'in
`fn_index` ve `trigger_id` değerlerini kaydet.

### 2.3. Şemayı doğrula — `/config` ve `/gradio_api/info`

- `/gradio_api/info` → `named_endpoints` altında her fonksiyonun parametre adları,
  varsayılanları, enum seçenekleri ve dönüş tipleri vardır.
- `/config` → `dependencies` listesinde hangi `fn_index` hangi `api_name`'e karşılık
  gelir, `inputs` (component id'leri) ve `outputs` nelerdir.

`data` dizisinin sırasını ** tahmin etme**: `/info` parametre sırası ile `/config`
`inputs` listesini çapraz kontrol et. Sonra HAR'daki gerçek `data` dizisiyle
karşılaştırarak doğrula (projede `verify` yaklaşımı: istemcinin ürettiği dizi ile
HAR'daki dizi birebir eşleşmeli).

### 2.4. Parametreleri nasıl ele almalı

- **Eksik parametre yok:** Gradio sabit uzunlukta dizi ister. Varsayılan değerleri
  de açıkça gönder (tarayıcı öyle yapar). Boş değerler `null`, `0.0`, `[]` veya
  boş dataframe sözlüğüdür.
- **Türetilen değerler:** Görsel slot'ları upload yanıtından üretilen FileData
  sözlüğüdür: `path`, `url` (`BASE + "/gradio_api/file=" + path`), `orig_name`,
  `size`, `mime_type`, `meta: {"_type": "gradio.FileData"}`.
- **Rastgele değerler:** `session_hash` 10 karakterli rastgele ID; `upload_id`
  rastgele ID. Seed mantığı projede tutarlı: elle sayı veya `randomize` bayrağı.
- **Atlanan adımlar:** Yalnızca UI görünürlüğünü değiştiren join'ler atlanır.

### 2.5. Başlıklar — minimum küme

İstemciler yalnızca şunları gönderir:
`accept`, `accept-language`, `origin`, `referer`, `user-agent`, `content-type`
(JSON isteklerinde). SSE için `accept: text/event-stream`.

**Bunların dışına çıkma.** Özellikle `x-zerogpu-*` başlıklarını ekleme (bkz. §1.1).

---

## 3. Proje düzeni ve yeni space ekleme

Dosya isimlendirmesi ve katmanlar mevcut yapıyı izler:

| Dosya | Görev |
|---|---|
| `<space>_client.py` | API istemcisi: upload + join + SSE + indirme, parametre dizisini üretir |
| `<space>_app.py` | tkinter arayüzü; `main()` fonksiyonu olmalı (launcher bunu çağırır) |
| `spaces.json` | Space kaydı: `id`, `ad`, `tur`, `space`, `host`, `modul`, `aciklama` |
| `settings_<space>.json` | Son kullanılan ayarlar (git'e girmez; `.gitignore`'a ekle) |
| `README.md` | Kullanım + teknik özet |

Ortak altyapı **`hf_image_client.py`** içindedir, yeniden kullanılır:
`ClientError`, `DEFAULT_UA`, `ProxyPool`, `RotatingTransport`
(`begin_run`, `post_json`, `post_multipart`, `open_sse`, `download_result`).
Yeni bir transport/proxy katmanı yazma.

İstemci şu davranışı korumalı:
- Her üretim tek proxy IP'sinden gider (`begin_run`); yeni üretimde sıradaki IP.
- Sonuç indirmesi proxy'siz denenir, 403/gerekirse üretim proxy'siyle tekrar denenir.
- Logcallback ile arayüze ilerleme/status iletilir.

---

## 4. Kontrol listesi (yeni space eklerken)

- [ ] HAR'dan yalnızca `*.hf.space` üretim istekleri çıkarıldı; HF/WAF/Stripe atıldı.
- [ ] `/info` + `/config` + gerçek `data` dizisi üçlü doğrulaması yapıldı.
- [ ] **Hiçbir yerde `x-zerogpu-uuid` / `x-zerogpu-token` yok** (grep ile kontrol et).
- [ ] Authorization / cookie / HF token yok.
- [ ] UI-only istekler atlandı, gerekli join'ler korundu.
- [ ] İstemci ortak transport/proxy katmanını kullanıyor.
- [ ] `spaces.json` kaydı eklendi; `modul` bir `main()` içeren dosyayı gösteriyor.
- [ ] `settings_<space>.json` `.gitignore`'a eklendi.
- [ ] README'de kullanım + teknik özet var.
- [ ] `python -m py_compile <yeni dosyalar>` ve import testi geçti.
- [ ] İstemcinin ürettiği `data` dizisi HAR'dakiyle birebir eşleşiyor.

---

## 5. Mevcut space'lerin kısa envanteri

| Space | Zincir | Not |
|---|---|---|
| `MiniMaxAI/minimax-h3-image` | join(fn 1) → SSE → join(fn 2, `[null]`) → SSE → PNG | Gorseller `data:` base64, ayrı upload yok |
| `rdata92/LTX-2.3-10eros` | upload → join(fn 0, 88 parametre) → SSE → MP4 | 88 elemanlı `data` |
| `wank3r/minimax-h3` | upload → join(fn 0, `_fit_keyframe`) → join(fn 1, 13 parametre) → SSE → MP4 | Canvas preset listesi `/info`'dan |
| `Intruzo/Krea-2-Turbo_v2` | upload → join(fn 4, 41 parametre) → SSE → PNG | `on_mode_change` join'i atlanır |
| `linoyts/qwen-image-2-1-realtime` | upload × N → join(fn 10 `/prepare`, 6 param) → join(fn 11 `/generate`, 5 param) → SSE → PNG | Gallery sarmalayıcısı; `push_live` önizleme join'leri atlanır |

Bu tabloya yeni space eklendiğinde güncelle.
