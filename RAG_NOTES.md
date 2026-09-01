# RAG Pipeline — Mimari, Bulgular ve Benchmark'lar

Son güncelleme: 2026-08-20

**Durum: CANLI.** Cloud Run servisi `eternate-ai-api`
(https://eternate-ai-api-368188768745.us-central1.run.app), proje
`renart-storefronts`, bölge `us-central1`. Zoho chat bot bu servisi çağırıyor.
Güncel revizyon **`eternate-ai-api-00013-ztp`**. Zoho tarafında güncellenmiş
`context handler` de canlıda.

Bu doküman `rag/` modüllerinin güncel durumunu, alınan kararları ve bu kararların
dayandığı ölçümleri kaydeder.

> **Metodoloji uyarısı — önce bunu oku.** Bu pipeline'da tek koşuluk ölçümler
> yanıltıcı. Aynı config, aynı context, aynı `temperature` ile 8 çağrıdan ~6'sı
> farklı metin üretiyor. Bir vaka 0/8 ile 5/8 arasında oynayabiliyor.
> **N=8'in altında karar verme.** Bu oturumda birden fazla yanlış sonuç, düşük
> N yüzünden alındı ve sonradan çürütüldü.

---

## 1. Pipeline

```
POST /chat  (x-api-key gerekli)
   → PARALEL BASLAT:
       analyze_query()          SINGLE/MULTI_FACT, rewrite, depends_on_history,
                                product_intent, product_name, budget_max/min
       retrieve(ham sorgu)      analyzer'i BEKLEMEDEN basliyor (bkz. bolum 10)
   → analysis hazir olunca:
       adaptive_retrieve_overlapped()  gerekiyorsa rewrite kolu + dedup + sort
       build_product_context()         Shopify: urun + koleksiyon (kendi icinde paralel)
   → generate_answer()      gemini-3.5-flash-lite
   → verify_links()         uydurma ürün linklerini düzeltir
```

| aşama | model | not |
|---|---|---|
| `query_analyzer.py` | `gemini-2.5-flash` | `thinking_budget=0`, `temperature=0` |
| `retriever.py` | `gemini-embedding-2` (768d) | Supabase pgvector, cosine |
| `generator.py` | `gemini-3.5-flash-lite` | `temperature=0.2` |
| `shopify.py` | — | Admin GraphQL 2024-01, ürün/koleksiyon/ağırlık |
| `product_context.py` | — | intent → Shopify → prompt metni |

Retrieval RPC'si (`match_knowledge_chunks`) sade cosine sıralaması:

```sql
select id, content, 1 - (embedding <=> query_embedding) as similarity
from eternate.knowledge_chunks
order by embedding <=> query_embedding
limit match_count;
```

### Neden iki kol retrieve ediliyor

SINGLE kolunda hem rewrite hem **ham sorgu** retrieve edilip birleştiriliyor.
Gerekçe: rewrite retrieval'ı iyileştirebildiği gibi bozabiliyor da. İki yönde
de hata yapıyor:

| hata | örnek |
|---|---|
| **kelime düşürme** | history platin kısıtı kurar, `"What about rose gold?"` → `"Are rose gold wedding bands available?"` — *platinum* düşer |
| **kısıt ekleme** | history custom ring'dir, `"What is your return policy?"` → `"...for custom-designed engagement rings?"` — müşteri bunu sormadı |

Ham kol her iki durumda da telafi ediyor. Ölçüm (eski korpus, 12 vaka): ham kolun
eklediği benzersiz chunk **28**, 12 vakanın 11'inde rewrite'ın getirmediğini
getirdi, 8 vakada örtüşme sıfır.

İki retrieval `ThreadPoolExecutor` ile paralel. `executor.map` girdi sırasını
koruduğu için sonuç deterministik. Seri → paralel: ort 2.00s → 1.32s.

---

## 2. Kurulum ve deploy düzeltmeleri

**`supabase==2.31.0`** kuruldu (tek eksik bağımlılıktı). `requirements.txt`
güncellendi. Not: kurulum `websockets`'i 16.1.1 → 15.0.1'e düşürdü (`realtime`
paketi `<16` istiyor).

**`rag/retriever.py` — env değişkeni isimleri.** `os.getenv("supabase_url")` →
`os.getenv("SUPABASE_URL")`. `.env`'de isimler büyük harf, `os.getenv`
case-sensitive. Windows'ta env değişkenleri case-insensitive olduğu için local'de
fark edilmiyordu — **Docker/Cloud Run'da (Linux) import anında patlardı.**

**`Dockerfile` — eksik klasör.** `COPY rag/ ./rag/` eklendi; yoksa deploy'da
`ModuleNotFoundError: No module named 'rag'`.

---

## 3. KÖK NEDEN: chunk'lama hatası

Uzun süre "model kapasitesi" ve "reranking gerekli" sanılan sorunların kaynağı
korpustaydı.

### Hata

`RAG/chunk.py` tüm dokümanları tek string'e yapıştırıp körlemesine kesiyordu:

```python
# ONCE - dokuman sinirlarini yok sayar
text = "\n\n".join(f"{d['title']}\n{d['content']}" for d in documents)
chunks = splitter.split_text(text)
```

Bir chunk, A dokümanının sonu + B dokümanının başı olabiliyordu. Oysa 171
dokümanın **151'i zaten 900 karakterin altındaydı** — bölünmeye ihtiyaçları yoktu.

```python
# SONRA - her dokuman ayri split edilir
for doc in documents:
    parts = splitter.split_text(f"{title}\n{content}")
    # uzun dokumanlar bolunuyor; her parcaya basligi geri ekle
    if len(parts) > 1 and title:
        parts = [p if p.startswith(title) else f"{title}\n{p}" for p in parts]
    chunks.extend(parts)
```

| | önce | sonra |
|---|---|---|
| chunk sayısı | 174 | 242 |
| **çok-konulu chunk** | **49 (%28)** | **1** |
| ortalama uzunluk | 675 char | 490 char |

### Neden her şeyi bozuyordu

Her chunk 2-3 konunun karışımı olduğu için embedding'i de **bulanık bir
ortalama** oluyordu. Hiçbir chunk hiçbir sorguya net benzemiyordu — similarity
skorları 0.70-0.78 bandına sıkışmıştı ve relevance ölçmüyordu.

Sonuçları:

- **Threshold budama imkânsızdı.** Doğru chunk 0.7665, alakasız chunk 0.7573 —
  arada 0.01.
- **Sort zararlıydı.** Skorlar anlamsız olduğu için "en yüksek skorluyu öne al"
  gürültüyü öne almak oluyordu.

Chunk'lar tek konulu olunca ikisi de tersine döndü. Vaka [9]'da doğru chunk
0.7618 → **0.8104**, 3. sıradan 1. sıraya çıktı.

### Neden 1:1 (her doküman = bir chunk) değil

Denendi ve elendi: en uzun doküman 15060 karakter ("Birthstone Guide", 12 ayın
taşı). Tek chunk olsaydı context'e ~3765 token gelir, dilution problemi doküman
sınırında geri gelirdi. Mevcut yaklaşım ortası: doküman sınırına saygı duy, uzun
olanı böl, başlığı her parçaya geri ekle.

### İkinci değişiklik: skora göre sıralama

`deduplicate_results` artık skora göre sıralıyor. İki retrieval kolu ayrı ayrı
geldiği için birleşik listede **global bir sıra yoktu** — kol sırasına göre
diziliyordu (önce rewrite'ın 3'ü, sonra ham'ın 3'ü).

### Ölçüm (N=8)

| vaka | başlangıç | + chunk düzeltmesi | + sort |
|---|---|---|---|
| [1] rose gold | 4/8 | 2/8 | **6/8** |
| [9] wedding band | 0/8 | 3/8 | **6/8** |

---

## 4. Model seçimi

Temiz korpusla, aynı context üzerinde (N=8):

| model | [1] | [9] | ort | med | max |
|---|---|---|---|---|---|
| 3.6-flash | 4/8 | **1/8** | **5.79s** | 5.37s | 9.01s |
| **3.5-flash-lite** ✓ | **5/8** | **7/8** | **0.77s** | 0.75s | 0.97s |
| 2.5-flash t=128 | **0/8** | 8/8 | 1.02s | 1.00s | 1.19s |

- **3.6** hem en yavaş hem en kötü. Vaka [9]'da 942 token düşünüp yine yanlış
  cevap veriyor. Uzun düşünmek gürültülü context'te avantajdı; gürültü kalkınca
  dezavantaja döndü.
- **2.5** vaka [1]'de sistematik hata (0/8): doğru chunk 1. sırada olmasına
  rağmen *"most items"* kısmını alıp *"other than platinum"* kısmını **atlıyor**.
  Fazla özetliyor. Bu müşteriye *yanlış* bilgi olarak gider; lite'ın hatası
  *eksik* bilgi.
- **Karar: lite.** Gerekçe latency değil (fark 0.3s); 2.5'in hatası
  yanlış-cevap sınıfında.

### `max_output_tokens` thinking token'larını da sayar

3.6'ya `max_output_tokens=250` konulduğunda **12/12 vaka kesildi** — model
bütçenin ~240'ını düşünmeye harcayıp cevaba 6-9 token bırakıyor. Token limiti
koyulacaksa 3.6 için **en az 400** gerekir. Ayrıca 3.6'da `thinking_budget=0`
→ 400 INVALID_ARGUMENT; `budget=1` gönderilse bile model ~230 token düşünüyor.
2.5'te `budget=0` çalışıyor ve gerçekten 0.

### `temperature=0` denendi — işe yaramadı

| | t=0.2 | t=0.0 |
|---|---|---|
| skor | **85/96** | 83/96 |
| senaryo başına benzersiz cevap | 6.2/8 | 5.8/8 |

`temperature=0` olmasına rağmen 8 çağrının ~6'sı farklı metin üretiyor. Varyansın
kaynağı sampling sıcaklığı değil — Gemini'de `temperature=0` deterministik değil.
**`temperature=0.2` kalsın.**

---

## 5. Follow-up (history) davranışı

### `depends_on_history`

`analyze_query` üçüncü bir alan döndürüyor. `false` ise (müşteri konu değiştirmiş)
rewrite kolu **atlanıyor**, yalnızca ham sorgu retrieve ediliyor — çünkü rewrite
o durumda sorulmayan kısıtı ekliyor.

Ölçüm: sınıflandırma **12/12 doğru**. Latency bedeli yok (analyzer +0.008s,
uçtan uca +0.05s). Retrieval çağrısı %9 azaldı (44 → 40).

### `FOLLOW-UP CONSTRAINTS` prompt kuralı

Gözlenen hata kalıbı: **model kısıtı görüyor, doğru chunk 1. sırada, ama cevabı
genel ürün bilgisiyle doldurup kısıtı belirtmeyi atlıyor.**

```
[5] "What about rose gold?"  (history: platin sadece beyaz)
    ✗ "Rose gold solid gold ürünlerde mevcut, bakır karışımıyla yapılır..."
    ✓ "Rose gold çoğu üründe mevcut, platin hariç."
```

`generator.py` system prompt'una eklenen kural (N=8, 12 senaryo):

| | mevcut | **kural A** ✓ | kural B |
|---|---|---|---|
| constraint | 26/32 | **32/32** | 30/32 |
| linked | 32/32 | 32/32 | 32/32 |
| topic_shift | 32/32 | 32/32 | 32/32 |

Kural A koşulsuz ve davranış tarifli. **Daha önce başarısız olan bir deneme
vardı**: o kural `"conflicts with a constraint"` koşuluna bağlıydı ve model
koşulu karşılanmamış sayıyordu ("rose gold çoğu üründe var" ile "platin sadece
beyaz" teknik olarak çelişmiyor). Ders: koşul değil, davranış tarif et.

### Query analyzer few-shot kontaminasyonu

`query_analyzer.py`'ye history eklenirken ilk few-shot örneği tam da test edilen
senaryoydu (platin/rose gold). Model history'yi okumak yerine örneği ezberden
tekrarlıyordu — history'siz ve alakasız history ile **aynı** çıktıyı veriyordu.
Örnek farklı bir konuyla değiştirilince kontaminasyon gitti.

---

## 6. Güncel benchmark sonuçları

### History'li — 12 senaryo × N=8

| tür | skor | ne test ediyor |
|---|---|---|
| linked | **32/32** | takip sorusu, history olmadan çözülemez (`"Which one is better?"`) |
| constraint | **30/32** | önceki turdaki kısıt taşınmalı |
| topic_shift | **32/32** | history var ama soru alakasız; bağlam bulaşmamalı |
| **toplam** | **94/96** | |

Kalan hata vaka [6] (`"Does that apply to wedding bands too?"`), 6/8. İzole
ölçümde 8/8 çıkmıştı — gerçek değer ~7/8, varyans içinde.

### History'siz — 27 senaryo

**26/27.** Kategoriler: simple, paraphrase, policy, numeric, multi_cond,
ambiguous, multi_fact, contradiction, unsupported.

### Latency

| ölçüm | değer |
|---|---|
| uçtan uca ort | **2.4-2.5s** |
| medyan | 2.2s |
| p90 | 3.3s |

Analyzer'ın kuyruk davranışı değişken: medyan 0.79s ama p90 3.19s, max 5.7s.

---

## 7. Shopify entegrasyonu (canlı katalog)

Ürün önerisi, fiyat ve ağırlık soruları mağazadan gerçek veriyle cevaplanıyor.

### Nasıl tetikleniyor

`analyze_query` üç alan daha döndürüyor; **ayrı bir sınıflandırıcı çağrısı yok**:

| alan | değerler |
|---|---|
| `product_intent` | `NONE` / `RECOMMEND` / `WEIGHT` |
| `product_name` | katalog arama terimi |
| `budget_max` / `budget_min` | USD, yoksa 0 |

Deluge bu işleri 3 ayrı Gemini çağrısıyla yapıyordu (intent onayı + ürün adı
çıkarma + yazım düzeltme). Analyzer zaten her mesajda çalıştığı için alan
eklemenin ölçülen maliyeti **+0.008s**.

### Shopify sorguları

REST değil **GraphQL** kullanılıyor. Gerekçe: katalogda **2.057 aktif ürün** var,
REST `products.json` 250 ile sınırlı ve sayfalama gerektiriyor.

| fonksiyon | ne getiriyor |
|---|---|
| `search_products` | başlık, **handle**, fiyat |
| `search_collections` | başlık, handle, ürün sayısı |
| `get_product_weight` | varyant ağırlıkları (`inventoryItem.measurement.weight`) |

**`handle` mutlaka Shopify'dan alınmalı.** Deluge başlıktan slug türetiyordu ve
404 üretiyordu:

```
başlık:  4mm Classic Flat Wedding Band
türetme: /products/4mm-classic-flat-wedding-band          ← 404
gerçek:  /products/4mm-classic-flat-womens-wedding-ring   ← 200
```

### Mağazanın veri özellikleri

- **Envanter takibi yok** (`tracksInventory=false`, made-to-order). `totalInventory`
  hep 0 döner, stok bilgisi verilmiyor. Gerçek gösterge `availableForSale`.
- **`variants.price` sorgu filtresi sessizce yok sayılıyor.** Bütçe filtresi
  Python tarafında yapılıyor.
- **Karat formatı `X.00 CT`** (`1.00`, `1.50`, `2.00`, `3.00`). Müşteri `3ct`
  yazıyor, katalog `3.00 CT`. Analyzer bu dönüşümü yapıyor — yapmazsa 102 ürün
  bulunamıyor.
- **Varyant seçenekleri başlıkta yok.** Doğum taşı, gem rengi, metal seçimi
  varyant; `aquamarine` araması 0 sonuç verir, `birthstone ring` 5 sonuç.

### Bütçe koleksiyonları

Mağazanın hazır koleksiyonları var (`gifts-under-250/500/1000`, `gifts-over-1000`).
Bütçe bir basamağa tam uyuyorsa gerçek koleksiyon, uymuyorsa filtre parametresi:

```
"under $250"    → /collections/gifts-under-250     (hazır koleksiyon)
"budget 100"    → /collections/gift-collection?filter.v.price.lte=100
"at least 1000" → /collections/gifts-over-1000
```

Link **her zaman koddan** geliyor; modele URL kurdurulmuyor.

### Boş `product_name` → hediye koleksiyonuna düş (2026-08-20)

Canlı konuşmada bulundu: *"I am looking for gifts"* hiç ürün/link getirmiyor,
model genel tavsiye veriyordu. *"Recommend me gifts"* ise bazen getiriyordu.

Teşhis (N=4): `product_intent` **doğru** (`RECOMMEND`), sorun `product_name`:

| sorgu | intent | product_name |
|---|---|---|
| "I am looking for gifts" | RECOMMEND ✅ | **boş** (4/4) |
| "Recommend me gifts" | RECOMMEND ✅ | boş (3/4), `gift` (1/4) |
| "I need to find a ring for my wife" | RECOMMEND ✅ | `ring` ✅ |

`_recommend_text` boş terimle Shopify'ı hiç aramıyor (`if term: ... else:
products = []`), katalog verisi üretilmiyor, prompt kuralı gereği
(*"When no LIVE CATALOG DATA section is present, do not name specific
products"*) model ürün adı veremiyor. **Sistem doğru davranıyor — ürün
uydurmuyor;** kök neden analyzer'ın boş terim döndürmesi.

Düzeltme: bütçe linki yoksa **ve** ürün bulunamadıysa gerçek `gift-collection`
linkine düş. Bütçe filtresinden *sonra* kontrol ediliyor, yani "bracelet +
$500" gibi filtre sonrası boşalan durumlar da kapsanıyor.

Talimat da ikiye ayrıldı — bu kritikti:

| durum | talimat |
|---|---|
| ürün var | "Recommend one or two specific products by name…" |
| ürün yok | **"Do not name any specific product"** + koleksiyona yönlendir |

Tek talimat bırakılsaydı ("iki ürün öner") model elinde ürün yokken **uydurmaya**
itilirdi.

| vaka | önce | sonra (canlı) |
|---|---|---|
| "I am looking for gifts" | link yok | **3/3 koleksiyon linki, 0 ürün** |
| "Recommend me gifts" | tutarsız | **3/3 koleksiyon linki, 0 ürün** |
| bracelet / ring | 2 ürün | değişmedi |
| return policy | linksiz | değişmedi |

### `verify_links` — uydurma link koruması

Prompt "linki aynen kullan" diyor ama yetmiyor: ölçümde **20 linkten 2'si**
uydurma çıktı. Model handle'ı "düzeltmeye" çalışıyor, başlıktaki kelimeleri
link'e enjekte ediyor:

```
Shopify: /products/4-prong-solitaire-moissanite-engagement-ring-1-50-ct-1   200
model  : /products/4-prong-solitaire-round-cut-moissanite-...-1-50-ct-1     404
                                     ^^^^^^^^^ basliktan enjekte
```

`product_context.verify_links()` cevaptaki her ürün linkini katalog verisiyle
karşılaştırıp en çok örtüşen gerçek link ile değiştiriyor. Deterministik, modele
bağlı değil.

---

## 8. Zoho chat bot entegrasyonu

Deluge scriptleri `Desktop\Zoho Chat bot scripts New\` altında.
Yedek: `backup-20260820-142712/`.

### Değiştirilen çağrı noktaları

| dosya | ne |
|---|---|
| `message handler.txt` | genel cevap çağrısı → `/chat` |
| `message handler - no keys.txt` | aynı |
| `context handler.txt` | 3 nokta: menü dışı soru, ürün alt menüsü, ürün önerisi |

**Dokunulmayanlar:** intent sınıflandırıcılar, sipariş takip/iade/değişim
akışları, menü yönlendirme, Desk ticket, `[TRANSFER_TO_AGENT]` işleme.

### Silinen ölü kod

Deluge, RAG'a bağlandıktan sonra da eski hazırlık işini yapmaya devam ediyordu:
Gemini'ye 2 çağrı + Shopify'a 3-4 REST çağrısı, sonuç `fullMsg`'e yazılıyor ama
API'ye `msg` gidiyordu. **Yani ~2-3 saniyelik iş çöpe gidiyordu.**

Silinenler: ağırlık bloğu, ürün önerisi bloğu, `sp1`/`sp2` prompt tanımları.
Dosyalar **%51 küçüldü** (72KB → 35KB).

### Aynı ölü kod `context handler`'da da vardı (2026-08-20)

Yukarıdaki temizlik **yalnızca message handler'a** uygulanmıştı. Context
handler'ın ürün önerisi kolunda (`product_rec`) aynı kalıp duruyordu:

| # | çağrı | ne getiriyordu |
|---|---|---|
| 1 | Gemini | yazım düzeltme (`spellFixedText`) |
| 2 | Shopify REST | `custom_collections.json?limit=250` |
| 3 | Shopify REST | `smart_collections.json?limit=250` |
| 4 | Shopify REST | `products.json?collection_id=…` |
| 5 | Shopify REST | `products.json?limit=100` |

Sonuç `catalogInstruction`'a yazılıyor, RAG'a ise yalnızca `recDetails`
gidiyordu — **değişkenin hiçbir kullanımı yoktu** (grep ile doğrulandı).
Üstüne Deluge bu JSON'ları döngüyle tarıyordu, yani ağ süresine CPU da
ekleniyordu.

O kod çalışsaydı bile FastAPI'ninkinden kötüydü: `limit=100`, katalogdaki
2.057 ürünün **ilk 100'ünü** görüyor. FastAPI GraphQL ile tümünde arıyor.

**Silindi: 339 satır** (3303 → 2964 satır, 129.6KB → 114.6KB, `invokeurl`
61 → 56). Ölü değişkenlerin 13'ü de 0 referans; parantez dengesi ve
`recDetails` sağlamlığı doğrulandı.

### `[TRANSFER_TO_AGENT]` context handler'da hiç işlenmiyordu

**Canlı konuşmada görüldü:** müşteri *"Need to speak with someone"* yazdı,
bot cevabın sonuna `[TRANSFER_TO_AGENT]` yazısını **ekranda gösterdi** ve
canlı desteğe **bağlamadı**. Müşteri ikinci kez yazmak zorunda kaldı.

İki katmanlı hata:

1. Satır 132'deki `mcHuman` kelime listesinde `"speak to someone"` var,
   müşteri **"speak WITH someone"** yazmış — eşleşme tutmadı, mesaj RAG'a düştü.
2. RAG doğru davranıp token üretti, ama **context handler'da token işleme
   kodu yoktu** (dosyada tek referans yoktu). Token ham haliyle `replies`'e
   girdi.

Message handler'da bu mantık zaten vardı (satır 647), context handler'a
taşınmamıştı.

Düzeltme: üç RAG çağrı noktasının **hepsine** token işleme bloğu eklendi.
Kelime listesine dokunulmadı — sonsuz varyasyon var ("need to talk with a
person", "can someone call me"); RAG zaten doğru karar veriyor, artık Deluge
onu dinliyor. Kelime listesi hızlı yol, RAG güvenlik ağı.

| durum | davranış |
|---|---|
| mesai içi | token temizlenir, `action=forward` → **canlı ajana bağlanır** |
| mesai dışı | token temizlenir, `agent_confirm` → onay → `agent_request` |

Mesai dışı akışı için context handler'ın **kendi** kalıbı kullanıldı
(`agent_confirm`); message handler orada Desk ticket açıyor. İkisi farklı ama
ikisi de doğru — farklı bağlamlar.

> **`agent_confirm` neden çoğu zaman görünmüyor:** yalnızca mesai **dışında**
> gösteriliyor. Mesai içinde (Pzt–Cum 10:00–21:00 ET) hem eski hem yeni kod
> doğrudan `action=forward` yapıyor — müşteri zaten insan istediğini söyledi,
> teyit sormak gereksiz sürtünme. Test ederken saate bak.

### Context handler'da RAG'dan ÖNCE 5 seri Gemini çağrısı var

`main_menu` dalında, kelime eşleşmelerinin hiçbiri tutmazsa sırayla çalışan
YES/NO sınıflandırıcıları: karşılaştırma alışverişi (460), kargolanmamış iade
(537), karşılaştırma alışverişi **tekrar** (599), sipariş takibi (680),
hasar/tamir (747). Hepsi `gemini-2.5-flash`.

Yani sıradan bir bilgi sorusu RAG'a ulaşmadan **5 model çağrısından** geçiyor;
kabaca **2.5–5s**. Üstüne RAG'ın kendi süresi biniyor.

- **460 ve 599 birebir aynı prompt** — biri gereksiz, ~0.5–1s bedava kazanç.
- Beşi analyzer'a `flow_intent` alanı olarak taşınabilir. Bölüm 7'deki kanıt:
  alan eklemenin ölçülen maliyeti **+0.008s**. Ama bu akış yönlendirmesini
  değiştirir; yanlış sınıflandırma müşteriyi yanlış akışa sokar, 100 senaryoluk
  prod testi yeniden koşulmalı. **Kalan en büyük latency kazancı.**

### Context handler'ın 3 RAG noktası history göndermiyor

Üçü de `ragHistory = ""` sabit (satır 785, 859, 1265 — silme öncesi
numaralar). Yalnızca message handler gerçek dönüşümü yapıyor. Yani bölüm
6'daki 32/32 linked/constraint skorları **o yolda geçerli değil**; menü
akışından gelen follow-up'lar bağlamsız cevaplanıyor.

### Gemini API anahtarı düz metin

`context handler.txt:11` ve `message handler.txt:7`'de anahtar açık yazılı.
Shopify ve Desk için Zoho **Connections** kullanılıyor
(`connection:"eternateshopify"`, `connection:"desk_write"`), Gemini için
kullanılmamış. `message handler - no keys.txt` anahtarları yer tutucuyla
değiştirilmiş kopya — token mantığı birebir aynı.

### History formatı

Desk hafızası HTML tutuyor, RAG düz metin bekliyor. Deluge tarafında dönüşüm var:
`<br>` → satır sonu, `Advisor:` → `Assistant:`. Model iki formatı da anlıyor
(test edildi), ama ölçümler temiz formatla alındığı için dönüştürülüyor.

### Akış tetikleyicileri katalogla çakışabiliyor

**Gerçek bug:** tamir akışı `msgLower.contains("prong")` ile tetikleniyordu.
Katalogda **92 üründe** "Prong" geçiyor (`4-Prong Solitaire...`). Bot kendi
önerdiği ürün hakkında soru sorulunca tamir akışına düşüyordu.

Düzeltme: `-prong` / `4 prong` / `6 prong` / `8 prong` ürün adı sayılıyor,
şikâyet sayılmıyor. Ayrıca `weight`, `weigh`, `how much is/does`, `price of`
kelimeleri akışları atlatıp RAG'a düşürüyor.

Kalan 20 tetikleyici katalogla çakışmıyor — ama katalog değişirse yeni
çakışmalar çıkabilir.

### Akış sınırı nerede

| müşteri der ki | ne olur |
|---|---|
| "track my order", "I want to exchange" | **sabit akış** + Shopify sipariş API'si |
| "what is your exchange policy" | **RAG** (`policy` kelimesi akışı atlatıyor) |
| "recommend a bracelet", "how much does it weigh" | **RAG** → Shopify katalog |

Sipariş takibi RAG'a hiç gitmiyor: e-posta doğrulaması + Shopify `orders` sorgusu
ile işliyor. Doğru tasarım — kişisel veri, doğrulama gerektiriyor.

---

## 9. Canlıya alma testi (100 senaryo)

`scratchpad/prodbench.py`, 10 kategori. İki katmanlı kontrol: LLM-judge (kalite)
+ otomatik (token, uydurma link, prompt sızıntısı).

**Sonuç: kalite 86/100, otomatik 100/100, latency ort 2.2s.**

| kategori | skor | kategori | skor |
|---|---|---|---|
| basit | 12/12 | koleksiyon | 10/10 |
| politika | 12/12 | **canlı destek** | **11/11** |
| karışık | 7/10 | **güvenlik** | **6/6** |
| history | 12/12 | bilinmeyen | 5/8 |
| ürün | 11/12 | belirsiz | 5/7 |

> **Judge'ın yanlış negatif oranı yüksek.** 14 FAIL'in 8'i judge hatasıydı:
> kriterleri Türkçe yazdığım için birebir ifade arıyor, ya da cevap doğru olduğu
> hâlde FAIL veriyor. Elle tasnif edilince gerçek başarı **~99/100**.
> Şüpheli FAIL'lerde cevabı ve KB'yi elle karşılaştır.

### Testte bulunan gerçek bug'lar

**1. Canlı destek token çakışması — en kritik olanıydı.** İki kural birbirini
iptal ediyordu: "yanlış/kayıp ürün → token" ile "context'ten cevaplanabilen
sorulara token verme". Model bilgi tabanında iade politikasını bulunca ikinciyi
uyguluyor, token'ı atlıyordu. Yani müşteri sorunlu siparişte insana bağlanamıyordu.

Kural netleştirildi: *politika açıklaması gerçek bir sipariş sorununu çözmez,
ikisini birden yap.* Sonuç: **11/11**, her senaryoda 4/4 tutarlı.

**2. "Are you an AI?"** — kaçamak cevap veriyordu. Deluge'da bu kural vardı,
taşınırken düşmüş. Eklendi.

**3. Eksik seçenek listeleme** — "hangi metaller var" sorusunda vermeil
düşüyordu (KB'de var, context'te 3. sırada). Prompt kuralı: *context'in saydığı
her şeyi listele; eksik bırakmak "sunmuyoruz" gibi okunuyor.* 0/1 → 5/6.

**4. Ürünle ilgili takip soruları katalog çekmiyordu.** `"how much is it"` →
`product_intent=NONE`, model *"I do not have pricing information"* diyordu.
`RECOMMEND` tanımı fiyat/link/mevcudiyet sorularını ve önceki turda konuşulan
ürüne dair takipleri kapsayacak şekilde genişletildi.

---

## 10. Latency optimizasyonu

Ürün soruları normal sorulardan ~1s yavaştı. İki paralelleştirme:

1. **`main.py`**: retrieval ile Shopify çağrısı aynı anda (ikisi de sadece
   `analysis`'e bağlı)
2. **`product_context.py`**: ürün araması ile koleksiyon araması paralel
   (0.66s → 0.38s)

| soru tipi | önce | sonra (canlı) |
|---|---|---|
| normal | ~2.1s | **1.96s** |
| ürün önerisi | ~3.2s | **2.20–2.33s** |
| ağırlık | ~2.9s | **2.15s** |

### Aşama aşama zaman haritası

Uçtan uca ölçmek nereyi optimize edeceğini söylemiyor. Aşama süreleri
(local, 6 vaka × N=3):

| aşama | ort | medyan | p90 | paralelleşiyor mu |
|---|---|---|---|---|
| **analyzer** | **0.91s** | 0.89s | 1.03s | ❌ zincirin başında, yalnız |
| retrieval | 0.78s | 0.72s | 0.96s | ✅ shopify ile |
| generator | 0.73s | 0.73s | 0.82s | ❌ son aşama |
| shopify | 0.14s | 0.00s | 0.43s | ✅ gizleniyor |

Analyzer tek başına toplamın **%38'i**. Retrieval'ın içi ise yarı yarıya:
**embedding 0.33s + pgvector 0.33s**.

`match_count` 3→10 yapıldığında pgvector süresi 0.31s→0.37s, yani neredeyse
değişmiyor. 241 chunk'ta cosine hesabı mikrosaniye — **o 0.33s hesaplama değil,
ağ gidiş-dönüşü.** Embedding cache fikri bu yüzden beklenenden az değerli:
cache hit olsa bile pgvector'ın payı duruyor.

### Analyzer ile ham retrieval'ı örtüştürme (2026-08-20)

`adaptive_retrieve`'in **bütün SINGLE yollarında ham sorgu retrieve ediliyor**:

| durum | ne yapılıyor | ham sorgu var mı |
|---|---|---|
| `rewritten == query` | `retrieve(query)` | ✅ |
| `depends_on_history == False` | `retrieve(query)` | ✅ |
| ikisi de değil | `_retrieve_many((rewritten, query))` | ✅ |

Ham sorgu müşterinin yazdığı metin — **analyzer'a ihtiyacı yok.** O yüzden
`adaptive_retrieve_overlapped()` ham kolu analyzer ile aynı anda başlatıyor;
ham kol analyzer'ın gölgesinde bitiyor, yani bedavaya geliyor.

`main.py` tarafında ek bir problem vardı: Shopify çağrısı `analysis`'e bağlı,
ama `analysis` artık retrieval işinin *içinde* üretiliyor. Retrieval'ın bitmesini
beklemek bugünkü paralelliği öldürürdü. Çözüm: `analysis_slot` adlı bir `Future`
— analyzer biter bitmez sonucu dışarı veriyor, ana thread Shopify'ı retrieval
bitmeden başlatabiliyor.

```
ÖNCE:  analyzer(0.91) ──→ retrieval(0.78) ──→ generator(0.73)   = 2.42s

SONRA: analyzer(0.91) ──┐
       ham retr(0.78) ──┴→ [rewrite kolu gerekirse] → generator  = 1.64s / 2.42s
```

- topic shift veya `ham == rewrite` → retrieval **tamamen bedava** (−0.78s)
- rewrite farklı → kazanç yok, rewrite kolu yine analyzer'ı beklemek zorunda

**Ölçüm (canlı, revizyon 00012):**

| soru tipi | önce | sonra |
|---|---|---|
| basit | 2.0–2.5s | **1.37–1.66s** |
| ürün önerisi | 2.1–2.6s | **1.75–2.08s** |

A/B (local, N=5, generator hariç): ort 1.63s → 1.21s, **%26**.

> **`match_count` tuzağı — eşdeğerlik testi yakaladı.** Ham kol spekülatif
> başlatıldığı için hangi dala gireceği henüz bilinmiyor, ama iki dalın
> ihtiyacı farklı: tek kol `match_count=5` (varsayılan), iki kol `3`
> (`_retrieve_many`'nin kullandığı). İlk yazımda ham kola `match_count`
> verilmemişti; iki-kol dalında 3 yerine 5 aday geliyordu ve **context'e
> düşük skorlu 2 fazladan chunk giriyordu** (bölüm 3'teki dilution problemi).
> Çözüm: 5 iste, iki-kol dalında ilk 3'ünü al.

> **`Future` + `set_exception`.** `analyze_query` patlarsa `set_result` hiç
> çağrılmaz ve `analysis_slot.result()` sonsuza kadar bekler — istek 120s
> timeout'a kadar asılı kalır. Eski kodda hata hemen yukarı fırlıyordu.
> `analyze_and_publish` içinde `try/except` ile `set_exception(exc)` çağrılıyor,
> böylece hata bekleyen thread'e iletiliyor ve istek hemen 500 dönüyor.

### Eşdeğerlik testi metodolojisi

Değişiklik yalnızca **çağrı sırası** olduğu için doğru test cevap puanlamak
değil, **retrieval çıktısının birebir aynılığı**. Cevap puanlamak analyzer ve
generator varyansını ölçer (metodoloji uyarısına bak), bizim değişikliği değil.
Eşdeğerlik burada daha güçlü bir kanıt: aynı girdi → aynı çıktı.

Her koşuda tek bir `analyze_query` çağrılıp **aynı `analysis` nesnesi iki
tarafa da veriliyor** — yoksa farkın kaynağı analyzer varyansı mı yoksa kodun
kendisi mi ayırt edilemez.

**Sonuç: 144/144 birebir aynı** (48 senaryo × N=3; chunk id + sıra + skor).
Senaryolar: `benchmark_answer_queries.py`'nin 27'si + 15 history + 6 ürün.

Dal kapsaması: `ham==rewrite` 80, `iki-kol` 39, `topic-shift` 16,
`MULTI_FACT` 9 — dördü de gerçekten kapsandı.

Ayrıca uçtan uca duman testi (FastAPI `TestClient`, 17 senaryo × N=2 = 34 istek):
HTTP kodu, boş cevap, prompt sızıntısı, `[TRANSFER_TO_AGENT]` doğruluğu,
uydurma link, deadlock. **34/34 temiz.**

### Cold start — ölçüldü, `min-instances=0` bilinçli tercih

`import main` = **1.03s** (local, sıcak disk). En pahalıları: `google.genai`
297ms, `supabase` 252ms, `fastapi` 244ms. Buna konteyner boot + `genai.Client()`
+ `create_client()` ekleniyor; gerçekçi cold start **2-6s**.

Client'lar modül seviyesinde kuruluyor (`retriever.py`, `query_analyzer.py`),
yani import anında çalışıyorlar — bölüm "Deploy"daki `genai.Client(api_key=None)`
patlaması da bu yüzdendi.

`min-instances=1` cold start'ı pratikte bitirir (~$10-18/ay). **Şimdilik 0'da
bırakıldı** — işletme kararı. Servis `startup-cpu-boost=true` ve
`containerConcurrency=80` ile çalışıyor; bir boot yüzlerce isteği amorti ediyor.

> Vercel'e taşıma değerlendirildi ve elendi. Cold start platform değil **model**
> seçimi — ölçekten sıfıra inen her sistemde var. Ayrıca: `ThreadPoolExecutor`
> paralelliği (bu pipeline'ın temel kazancı) orada garanti değil, Gemini/Supabase
> çağrıları aynı ağ omurgasını kaybeder, 63MB bağımlılık limite yaklaşır ve
> bütün ölçümlerin yeniden alınması gerekirdi.

---

## 11. Bilgi tabanı düzeltmeleri

Sistemin doğru çalıştığı ama **kaynak verinin yanlış** olduğu durumlar. Bunlar
kod değil içerik sorunu; `RAG/knowledge/reviewed/knowledge_structured.json`
düzeltilip yeniden chunk + ingest gerekiyor.

| konu | sorun | çözüm |
|---|---|---|
| **GOLDENVOICE** | Trustpilot yorumu karşılığı %20 indirim kodu paylaşılıyordu | doküman silindi; `prompts.py`'den de |
| **SPARKS** | ikinci sipariş indirim kodu veriliyordu | kaldırıldı, "kod paylaşma, service@eternate.com'a yönlendir" |
| **Return Portal** | *"Returns can be checked through the Return Portal"* — yanlış, portal sadece talep oluşturmak için | "durum göstermez, ekip e-posta atar" |
| **Yüzük bedeni** | `prompts.py` "7mm+ → 0.25 beden", KB "5mm+ → bir beden" | `prompts.py` KB'ye uyduruldu (3 yerde) |

Loyalty Club dokümanındaki Trustpilot referansı **kaldı** — orada indirim kodu
değil, sadakat puanı anlatılıyor.

### AÇIK: ring size guide linki ana dokümanlarda yok (2026-08-20)

Canlı konuşmada bulundu:

```
"can you give me the link"  → "You can find our ring sizing guide on our website"
"give me product link"      → "You can download our Ring Size Guide from our website"
```

Model **"our website" diyor ama link vermiyor.** Doğru davranıyor — elinde
link yok, uydurmuyor.

Ölçüm: "link ver" sorgusunda gelen 6 chunk'ın ilk üçü ring-size ile ilgili ve
**hiçbirinde URL yok** (`link_sayisi=0`). Link KB'de var ama yalnızca
*"Which ring size should I order for wide bands?"* adlı **dar kapsamlı** bir
dokümanda; ana doküman *"How To Measure Your Ring Size"* (2885 karakter) linki
hiç içermiyor. Retrieval doğal olarak ana dokümanları getiriyor, linkli olan
semantik olarak uzak kalıyor.

Düzeltme: `knowledge_structured.json`'daki ana ring-size dokümanlarına
`https://eternate.com/pages/how-to-measure-your-ring-size` eklenmeli, sonra
yeniden chunk + ingest. **Yapılmadı.** Diğer sık istenen sayfaların (return
portal, size chart) da taranması gerekir — bu muhtemelen tek vaka değil.

### AÇIK: model canlı desteğe aktarırken telefon numarası veriyor

`generator.py` prompt'u açıkça yasaklıyor:

```
Never tell the customer to contact customer service, to email us, or to
call us themselves, and never say you cannot help.
```

Ama ölçümde (canlı, N=6 × 3 vaka):

| vaka | token | telefon numarası |
|---|---|---|
| "Need to speak with someone" | 6/6 ✅ | **6/6 veriyor** ❌ |
| "I want to talk to a human" | 6/6 ✅ | **4/6 veriyor** ❌ |
| "My order arrived with the wrong ring" | 6/6 ✅ | 0/6 ✅ |

Token tarafı kusursuz (18/18). Sorun dar: **müşteri açıkça insan istediğinde**
model `+1 (844) 588 4370` numarasını veriyor — 10/12. Sipariş sorunu
vakalarında vermiyor, yani kuralın o kısmı çalışıyor.

Model numarayı *bilgi vermek* sanıyor, *yönlendirme* saymıyor. Bölüm 5'teki
dersle aynı kalıp: **koşul değil, davranış tarif et.** Düzeltme yapılmadı.

Güncel bilgi tabanı: **170 doküman → 241 chunk**.

> **Bilinen tutarsızlık:** 14K altın oranı iki chunk'ta farklı gösteriliyor —
> biri `58.3%`, diğeri `585` damga kodu. Model 6 denemede 5 kez `58.5%`, 1 kez
> `58.3%` dedi. İkisi de teknik olarak yanlış değil ama müşteri farklı rakam
> duyabilir. İşletme kararı bekliyor.

---

## 12. Reranker değerlendirmesi — GEREKMİYOR

Öneri şuydu: *"retriever semantik yakınlığa bakıyor, bu chunk soruyu cevaplıyor
mu bakmıyor; local cross-encoder ile yeniden sıralayalım."*

Teşhis doğruydu ama sebep retriever değil, ona verilen bozuk chunk'lardı.
Reranker o durumda semptomu **maskeleyecekti**: 3 konu içeren bir chunk'a
"kısmen alakalı" deyip yine context'e alacak, gürültü de beraberinde gelecekti.

Kök neden düzeltildikten sonra yer kalmadı:

- Retrieval doğru chunk'ı getiriyor ve 1. sıraya koyuyor
- Kalan hatalar generation tarafında — doğru chunk context'te ve üst sırada
  olmasına rağmen model bilgiyi cevaba koymuyor
- Cloud Run'da cross-encoder cold start (+3-8s/instance) ve ~300-600ms/istek
  maliyeti getirirdi

**Aynı gerekçe hybrid search / XGBoost learning-to-rank / fine-tuned embedding
için de geçerli.** Hepsi "doğru chunk'ı bul ve öne al" problemini çözer; o
problem çözülmüş durumda. Hybrid search'ün (BM25) mantıklı olabileceği tek yer
tam kelime eşleşmesi gereken sorgular (ürün kodu, "BD series", "14K") — ama
ölçümde bu tür bir hata görülmedi.

> **Ders:** retrieval'ın çıktısını iyileştirmeye çalışmadan önce girdisini
> doğrula. Threshold ve sort da bozuk korpusta test edilip "işe yaramaz" diye
> elenmişti — ikisi de aslında elenmemişti, o veriyle ölçülemiyordu.

---

## 13. DİKKAT: `RAG/src/rag/` eski nesil

`RAG/src/rag/` altında `rag/` modüllerinin **ikinci bir kopyası** var ve güncel
değil:

| | `rag/` (fastApi, canlı) | `RAG/src/rag/` (eski) |
|---|---|---|
| generator modeli | `gemini-3.5-flash-lite` | `gemini-2.5-flash` |
| skora göre sıralama | var | **yok** |
| paralel retrieval | var | **yok** |
| `depends_on_history` | var | **yok** |

`RAG/benchmark_answers.py` bu eski kopyayı import ediyor (`sys.path.insert` ile
`src/`). O harness'ı olduğu gibi çalıştırmak **yanlış şeyi ölçer**.
Senkronize edilmeli ya da silinmeli.

---

## Değişen dosyalar

| Dosya | Değişiklik |
|---|---|
| `requirements.txt` | supabase + bağımlılıkları; websockets 15.0.1 |
| `Dockerfile` | `COPY rag/ ./rag/` |
| `rag/retriever.py` | env isimleri büyük harf |
| `rag/query_analyzer.py` | `history` parametresi, FOLLOW-UP HANDLING, `depends_on_history` |
| `rag/adaptive_retriever.py` | rewrite+ham birleşimi, paralel retrieval, skora göre sıralama, topic-shift'te tek kol; **`adaptive_retrieve_overlapped()`** (bölüm 10) |
| `rag/generator.py` | model → `gemini-3.5-flash-lite`, `FOLLOW-UP CONSTRAINTS` kuralı |
| `main.py` | `/chat`: auth, paralel retrieval+Shopify, `verify_links`; **analyzer/ham-retrieval örtüşmesi (`Future` ile `analysis_slot`)** |
| `rag/shopify.py` | **yeni** — Admin GraphQL: ürün, koleksiyon, ağırlık |
| `rag/product_context.py` | **yeni** — intent → Shopify → prompt metni, bütçe, link doğrulama; **boş `product_name` → gift collection fallback + duruma göre talimat** |
| `prompts.py` | beden kuralı KB ile uyumlu; GOLDENVOICE/SPARKS silindi |
| `RAG/chunk.py` | doküman başına split; kullanılmayan embed çağrısı kaldırıldı |
| `RAG/ingest_test.py` | ingest öncesi tabloyu temizliyor |
| Zoho `message handler` ×2 | RAG API çağrısı, ölü kod temizliği, prong düzeltmesi |
| Zoho `context handler` | 3 çağrı noktası RAG API'ye; **339 satır ölü Shopify/Gemini kodu silindi**; **`[TRANSFER_TO_AGENT]` işleme 3 noktaya eklendi** |

### Deploy

```
gcloud run deploy eternate-ai-api --source . --project renart-storefronts   --region us-central1 --allow-unauthenticated --env-vars-file env.yaml   --memory 1Gi --cpu 1 --timeout 120 --min-instances 0 --max-instances 10
```

`env.yaml` `.env`'den üretilir (komut `commands.txt`'te), git ve Docker'dan
dışlanır. **9 env değişkeni gerekiyor** — ilk deploy denemesi başarısız oldu
çünkü serviste yalnızca 4 tanesi vardı; `rag/query_analyzer.py` import anında
`genai.Client(api_key=None)` ile patlıyor ve konteyner port dinleyemiyor.

### Düzeltilen bug'lar

**`adaptive_retrieve` MULTI_FACT'te `None` dönüyordu.** `depends_on_history`
eklenirken fonksiyonun son `return _retrieve_many(analysis.queries, retrieve_fn)`
satırı düşmüştü. MULTI_FACT sorgularda `/chat` 500 verirdi. Geri kondu.

**Canlı destek token'ı sorunlu siparişlerde gelmiyordu.** Bölüm 9.

**`prong` akış çakışması.** Bölüm 8.

**Ürün takip soruları katalog çekmiyordu** (`"how much is it"`). Bölüm 9.

**Karat formatı eşleşmiyordu** (`3ct` vs `3.00 CT`). Bölüm 7.

**Model ürün handle'ını değiştirip 404 üretiyordu.** `verify_links`, bölüm 7.

**`[TRANSFER_TO_AGENT]` context handler'da işlenmiyordu** — token müşteriye
görünüyor, canlı desteğe bağlanmıyordu. Bölüm 8.

**Context handler'da 339 satır ölü Shopify/Gemini kodu.** Bölüm 8.

**Boş `product_name` ile ürün önerisi eli boş dönüyordu** (*"I am looking for
gifts"*). Bölüm 7.

**Ham kol spekülatif başlatılırken `match_count` atlanmıştı** — iki-kol
dalında context'e 2 fazladan düşük skorlu chunk giriyordu. Eşdeğerlik testi
yakaladı. Bölüm 10.

## Benchmark dosyaları

Kalıcı: `RAG/benchmark_answer_queries.py` (27 senaryo, `must_include`/`must_not`
alanlarıyla).

Scratchpad (kalıcı değil):
- `prodcases.json` + `prodbench.py` — **100 senaryo, canlıya alma testi**
- `histcases.json` + `final_verify.py` — 12 history senaryosu, N=8
- `intentcases.json` + `intentbench.py` — 18 ürün-intent senaryosu + regresyon
- `promptbench.py`, `tempbench.py`, `bench27.py`

Saklanmak isteniyorsa repo içine taşınmalı.

Skorlama **LLM-judge** ile (`gemini-2.5-flash`, `thinking_budget=256`), çünkü
`must_include` doğal dil ifadeler ve regex ile eşleşmiyor. Judge'ın kendi hata
payı var: bu oturumda iki kez yanlış negatif üretti (cevap KB ile uyumluyken
FAIL verdi). Şüpheli FAIL'lerde cevabı ve KB'yi elle karşılaştır.

---

## Bekleyen işler

Hepsi ölçülmüş durumda; hiçbiri yapılmadı.

| # | iş | kazanç / etki | risk | bölüm |
|---|---|---|---|---|
| 1 | Context handler'daki 5 seri Gemini sınıflandırıcısını analyzer'a `flow_intent` alanı olarak taşı | **2.5–5s** | **yüksek** — akış yönlendirmesi değişir, 100 senaryo yeniden koşulmalı | 8 |
| 2 | 460 / 599 birebir aynı sınıflandırıcı — birini sil | ~0.5–1s | düşük | 8 |
| 3 | Ana ring-size dokümanlarına guide linkini ekle + yeniden ingest; diğer sık sayfaları da tara | müşteri link istediğinde link alır | yok | 11 |
| 4 | `generator.py`'ye "aktarırken iletişim bilgisi verme" kuralı — davranış tarifli, koşulsuz | 10/12 vakada telefon numarası sızıyor | düşük, N=8 ölç | 11 |
| 5 | Context handler'ın 3 RAG noktasına history bağla | menü akışındaki follow-up'lar bağlamsız | düşük–orta | 8 |
| 6 | Gemini anahtarını Zoho Connection'a taşı | güvenlik | yok | 8 |
| 7 | `min-instances=1` | cold start 2–6s → 0 | yok, ~$10–18/ay | 10 |
| 8 | `RAG/src/rag/` eski kopyayı sil ya da senkronize et | benchmark yanlış kodu ölçüyor | yok | 13 |

Denenip **elenenler** (yeniden gündeme gelirse gerekçeye bak): reranker /
hybrid search / learning-to-rank (bölüm 12), `temperature=0` (bölüm 4),
Vercel'e taşıma (bölüm 10), embedding cache (bölüm 10 — pgvector payı yüzünden
beklenenden az değerli).
