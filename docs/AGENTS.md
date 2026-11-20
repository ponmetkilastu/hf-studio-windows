# Yerel HF Image/Video API — Agent Kullanım Kılavuzu


Tek endpoint'e istek atarsın, karşılığında dosya (PNG / JPEG / MP4) alırsın.

## Bağlantı

- **Base URL:** `http://127.0.0.1:8787`
- **Auth:** yok.
- Sunucu zaten ayakta değilse başlat: `C:\Users\ozan\Desktop\huggingface\api_baslat.bat` veya `cd C:\Users\ozan\Desktop\hugginface` → `python core/local_api.py`
- `GET http://127.0.0.1:8787/` → endpoint listesi ve durum.
- Tarayıcıdan manuel test: `docs\test.html` (çift tıkla aç; API adresi hazır gelir).



---

## Endpoint'ler

| Endpoint | Ne yapar | Zorunlu alanlar | Dönen dosya |
|---|---|---|---|
| `POST /ph3/text2image` | Metinden görsel (hızlı, önerilen) | `prompt` | JPEG |
| `POST /ph3/img2img` | Görseli düzenle | `image`, `instruction` | JPEG |
| `POST /krea/text2image` | Metinden görsel (farklı model) | `prompt` | PNG |
| `POST /krea/img2img` | Görseli düzenle | `image`, `prompt` | PNG |
| `POST /qwen/text2image` | Metinden görsel | `prompt` | PNG |
| `POST /qwen/img2img` | Görsel(ler)le üret/düzenle | `prompt` | PNG |
| `POST /minimax-video/i2v` | Fotoğraftan video | `image`, `prompt` | MP4 |
| `POST /ltx/i2v` | Fotoğraftan video (başka model) | `image`, `prompt` | MP4 |
| `POST /minimax-image/text2image` | Metinden görsel (başka model) | `prompt` | PNG |
| `POST /zimage/text2image` | Metinden hızlı görsel (Z-Image Turbo) | `prompt` | PNG |
| `POST /ltx09/i2v` | Fotoğraftan video (LTX-Video Distilled) | `image`, `prompt` | MP4 |
| `POST /ltx25/i2v` | Metinden / fotoğraftan video (LTX-2.5) | `prompt` (image opsiyonel) | MP4 |
| `POST /trellis2/image3d` | Görselden 3D model (TRELLIS.2) | `image` | GLB |
| `POST /kokoro/tts` | Metinden ses (Kokoro TTS) | `text` | WAV |
| `POST /gemma/chat` | Sohbet (Gemma 4 31B) | `message` | JSON (`content`) |
| `POST /wan22/i2v` | Fotoğraftan video (Wan 2.2 Fast, 14B + Lightning LoRA) | `image` | MP4 |

---

## İstek formatı

**Tüm alanlar `multipart/form-data` olarak gönderilir** (FastAPI `Form` / `File` bekler).
Dosya alanlarına `UploadFile` (curl `-F`, Python `files=`, JS `FormData.append`) verilir.

---

## Parametreler

### Metin üretimi

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `prompt` | Üretilecek şeyin tarifi | — (zorunlu) |
| `seed` | Tam sayı | modele göre 0 / 2 / 42 |
| `randomize` | `true` ise seed rastgele | model default |
| `aspect` | `4:3`, `1:1`, `16:9`, `9:16`, `Auto` … | `4:3` / `Auto` |
| `resolution` | ph3: `8 MP`/`4 MP`… · qwen: `512`/`1024`/`1536` | model default |
| `upsample` | `true`/`false` | model default |

### img2img (görsel düzenleme)

| Parametre | Açıklama |
|---|---|
| `image` | Düzenlenecek kaynak görsel (ph3/krea/minimax-video/ltx) |
| `instruction` (ph3) / `prompt` (krea) | Ne değiştirmek istediğin |
| `ref2`…`ref8` (ph3), `image`+`ref1`…`ref10` (qwen) | Ek referans görseller |
| `width`, `height`, `steps`, `cfg`, `sampler` (krea) | İnce ayar |

### Video

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `image` | Başlangıç görseli | — (zorunlu) |
| `prompt` | Hareket tarifi | — (zorunlu) |
| `duration` / `seconds` | Süre (sn) | 5 / 4 |
| `steps` | Örnekleme adımı | 25 |

Wan 2.2 Fast (`/wan22/i2v`) alanları: `image`, `prompt`, `negative_prompt`,
`steps` (1–30, vars. 6), `duration` (0.5–5 sn, vars. 3.5), `guidance_scale`
ve `guidance_scale_2` (0–10, vars. 1), `seed` (vars. 42), `randomize` (vars. `true`).

### Görselden 3D (TRELLIS.2)

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `image` | 3D'ye çevrilecek görsel (alpha maskeli önerilir) | — (zorunlu) |
| `resolution` | `512` / `1024` / `1536` | `1024` |
| `seed` | Tam sayı (0–2147483647) | `0` |
| `randomize` | `true` ise seed rastgele | `true` |
| `decimation_target` | Hedef yüz sayısı (100000–500000) | `300000` |
| `texture_size` | Doku çözünürlüğü (1024–4096) | `2048` |
| `ss_*`, `shape_slat_*`, `tex_slat_*` | 3 aşama ince ayar (`guidance_strength`, `guidance_rescale`, `sampling_steps`, `rescale_t`) | model varsayılanları |

---

## Örnekler

### Python (önerilen)

```python
import requests
BASE = "http://127.0.0.1:8787"

# Metinden görsel
r = requests.post(f"{BASE}/ph3/text2image",
                  data={"prompt": "a cinematic portrait", "seed": 42}, timeout=240)
r.raise_for_status()
open("out.jpg", "wb").write(r.content)

# Görseli düzenle
r = requests.post(f"{BASE}/ph3/img2img",
                  files={"image": open("src.jpg", "rb")},
                  data={"instruction": "make her smile"}, timeout=240)
r.raise_for_status()
open("edited.jpg", "wb").write(r.content)

# Fotoğraftan video
r = requests.post(f"{BASE}/minimax-video/i2v",
                  files={"image": open("src.jpg", "rb")},
                  data={"prompt": "slow camera push in"}, timeout=600)
r.raise_for_status()
open("video.mp4", "wb").write(r.content)
```

### JavaScript / Node

```js
const BASE = "http://127.0.0.1:8787";

async function text2image(prompt) {
  const fd = new FormData();
  fd.append("prompt", prompt);
  fd.append("seed", "42");
  const r = await fetch(`${BASE}/ph3/text2image`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return await r.blob();
}

async function img2img(file, instruction) {
  const fd = new FormData();
  fd.append("image", file);
  fd.append("instruction", instruction);
  const r = await fetch(`${BASE}/ph3/img2img`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return await r.blob();
}
```

### curl

```bash
curl -X POST http://127.0.0.1:8787/ph3/text2image \
  -F "prompt=a cinematic portrait" -F "seed=42" -o out.jpg

curl -X POST http://127.0.0.1:8787/ph3/img2img \
  -F "image=@src.jpg" -F "instruction=make her smile" -o edited.jpg

curl -X POST http://127.0.0.1:8787/minimax-video/i2v \
  -F "image=@src.jpg" -F "prompt=slow camera push in" -o video.mp4
```

---

## Hangisini seçmelisin?

| İstek | Endpoint |
|---|---|
| Metinden hızlı görsel | `/ph3/text2image` |
| Fotoğraf düzenleme | `/ph3/img2img` |
| Farklı görsel stili / yüksek kalite | `/krea/text2image` |
| Referans görsellerle tutarlılık | `/qwen/img2img` |
| Fotoğraftan video | `/minimax-video/i2v` |
| Hızlı metinden görsel (Z-Image Turbo) | `/zimage/text2image` |
| Fotoğraftan video (LTX Distilled) | `/ltx09/i2v` |
| Metinden / fotoğraftan video (LTX-2.5) | `/ltx25/i2v` |
| Görselden 3D model (GLB) | `/trellis2/image3d` |
| Metinden ses (Kokoro TTS) | `/kokoro/tts` |
| Sohbet | `/gemma/chat` |
| Fotoğraftan video (Wan 2.2 Fast) | `/wan22/i2v` |

Belirtilmezse varsayılan olarak `/ph3/text2image` kullan.

---

## Davranış notları

- Endpoint üretim bitene kadar **bekler**, sonra doğrudan dosya döndürür.
- Görsel üretimi genelde **15–35 saniye**, video **1–5 dakika** sürer → timeout'u buna göre ayarla.
- Hata olursa JSON döner: `{"ok": false, "error": "..."}` (HTTP 500).
- Dönen dosyanın tipi `Content-Type` başlığında: `image/png`, `image/jpeg`, `video/mp4`.
- Sunucu `C:\Users\ozan\Desktop\hugginface\core\local_api.py` — agent aynı bilgisayarda olduğu için `127.0.0.1` çalışır.
