# Policy Gap Report

`SYSTEM_PROMPT` sadeleştirmesi sırasında RAG karşılığı **yetersiz** bulunan ve bu
nedenle prompt'ta **bırakılan** policy alanları.

Yöntem: her policy başlığı için Supabase knowledge base'e anlamsal sorgu atıldı
(`gemini-embedding-2`, 768d, top-3). Eşik: `>= 0.75` yeterli, `0.68-0.75` zayıf,
`< 0.68` boşluk. Zayıf ve boşluk çıkanlar ayrıca literal `ILIKE` taramasıyla
doğrulandı.

Toplam chunk sayısı: 241

---

## 1. Duplicate charges / çift çekim / eksik iade

**Prompt bölümü:** `DUPLICATE CHARGES, CANCELED ORDERS, AND REFUND STATUS`
**Durum:** Promptta bırakıldı.

**Neden yetersiz:** En iyi anlamsal eşleşme 0.6489 ("package lost or damaged") —
konuyla ilgisiz. Literal tarama (`duplicate charge`, `charged twice`,
`double charge`, `pending authorization`) **hiçbir kayıt döndürmedi**.

Bu bölüm çoğunlukla davranış kuralı (iade yapıldığını iddia etme, kart bilgisi
isteme, banka davranışı hakkında spekülasyon yapma) olduğu için zaten korunacaktı;
ancak altında yatan olgusal zemin de RAG'de yok.

**Önerilen chunk:**

> **Başlık:** What happens if I was charged twice or see an unexpected charge?
>
> **İçerik:** If a customer sees a duplicate or unexpected charge, the payment
> status of the relevant order must be reviewed by our team before anything is
> confirmed. Some charges appear as temporary authorization holds that are
> released by the bank rather than as completed payments. Release timing is
> determined by the customer's bank, not by Eternate.

---

## 2. Refund timing (iptal dışı bağlamlar)

**Prompt bölümü:** `CANCELLATION AND REFUND SEPARATION` (koruma kuralı olarak kaldı)
**Durum:** Promptta davranış kuralı olarak bırakıldı.

**Neden yetersiz:** Anlamsal eşleşme 0.6848. İade süresi bilgisi knowledge base'de
**yalnızca** chunk 695 (`How can I cancel the order?`) içinde ve orada da iptal
bağlamına koşullanmış durumda ("If a cancellation is completed, refunds usually
take 3-5 business days"). İade/return kaynaklı geri ödeme süresi için bağımsız bir
chunk yok.

**Önerilen chunk:**

> **Başlık:** How long does a refund take after a return is processed?
>
> **İçerik:** Once a return is received and approved, the refund is issued to the
> original payment method. It usually takes 3-5 business days for the funds to
> appear in the account, depending on the bank or payment provider.

---

## 3. Plant a Tree programı

**Prompt bölümü:** Kaldırıldı (`PLANT A TREE PROGRAM`)
**Durum:** ⚠️ Kaldırıldı ancak RAG karşılığı **zayıf**.

**Neden zayıf:** Anlamsal eşleşme 0.7128 — genel sürdürülebilirlik chunk'ı
(`How does Eternate contribute to sustainability?`). Literal `plant a tree`
taraması yalnızca chunk 665'i (`About Us`, genel sosyal sorumluluk metni) buldu;
programın kendisine dair spesifik bir chunk yok.

**Not:** Bu bir policy değil pazarlama bilgisi olduğu için kaldırma riski düşük —
bot bilgi yokken uydurmak yerine "team must verify" diyecektir. Yine de tam
karşılık isteniyorsa aşağıdaki chunk eklenebilir.

**Önerilen chunk:**

> **Başlık:** What is the Eternate plant a tree program?
>
> **İçerik:** Eternate plants a tree for eligible orders as part of its
> environmental commitment. Current program details and which orders qualify are
> confirmed by the team.

---

## 4. Promise ring ürün detayı

**Prompt bölümü:** Kaldırıldı (`PROMISE RINGS`)
**Durum:** Kaldırıldı — RAG karşılığı **yeterli**.

Anlamsal sorgu ilk denemede 0.7437 ile zayıf göründü, ancak literal tarama
chunk 799'u ortaya çıkardı: *"All promise rings are currently made with
moissanites and pink moissanites..."* — prompt'taki bilginin tamamını karşılıyor.
Ayrıca chunk 790 ürün kategorileri listesinde promise ring'leri sayıyor.

Boşluk **yok**, kayıt amaçlı listelendi.

---

## Özet

| # | Alan | Durum | Aksiyon |
|---|------|-------|---------|
| 1 | Duplicate charges | Boşluk (0.6489) | Promptta tutuldu + chunk önerildi |
| 2 | Refund timing (return) | Zayıf (0.6848) | Promptta tutuldu + chunk önerildi |
| 3 | Plant a Tree | Zayıf (0.7128) | Kaldırıldı, chunk önerildi |
| 4 | Promise rings | Yeterli (literal doğrulama) | Kaldırıldı, aksiyon yok |

Talimat gereği Supabase'e **hiçbir chunk eklenmedi veya değiştirilmedi**. Yukarıdaki
öneriler admin projesi (`eternate-knowledge-admin`) üzerinden eklenmelidir.
