**TEKNİK ÖZET · AĞUSTOS 2026**

# Eternate RAG Asistanı

![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)
![Google Cloud Run](https://img.shields.io/badge/Cloud%20Run-deployed-4285F4?logo=googlecloud&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-embedding%20%2B%20flash-8E75B2?logo=googlegemini&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-pgvector-3FCF8E?logo=supabase&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-slim-2496ED?logo=docker&logoColor=white)

Müşteri sorularını kendi başına yanıtlayan, mağazanın canlı ürün verisine bağlı bir destek sistemi. Zoho üzerindeki eski kurulumdan taşındı, her değişiklik ölçülerek doğrulandı.

**[🔗 Canlı Demo / Tam Rapor](https://claude.ai/code/artifact/ebde35b6-a53f-499d-a4a4-27a1df755d06)**

> **RAG nedir?** Açılımı "bilgi getirerek üretim" (retrieval-augmented generation). Yapay zekâya her şeyi ezberletmek yerine, soru geldiği anda şirketin kendi belgelerinden en alakalı kısımları bulup önüne koyma yöntemi. Model de cevabı yalnızca o bilgiyle yazıyor — böylece bilgi güncellendiğinde modeli yeniden eğitmek gerekmiyor, ve model uydurmak yerine elindeki kaynağa dayanıyor.

Geliştiren **Ali Bacık** · Python · FastAPI · Google Cloud Run

## Asıl yapısal fark

*İki sistem bilgiyi tamamen farklı şekilde taşıyor.*

Eski sistemde şirketin **tüm bilgisi her mesajda** yapay zekâya gönderiliyordu. Birisi sadece "Kanada'ya gönderiyor musunuz?" diye sorduğunda bile gravür ücretleri, garanti kapsamı ve doğum taşı listesi de beraberinde gidiyordu.

Bunun iki bedeli vardı: her istek daha pahalı ve yavaştı, ve ilgili bilgi alakasız bilginin içinde kayboluyordu.

**Yeni yaklaşım: anlam bazlı arama**

Bilgi tabanı 242 parçaya bölünmüş ve her parça, *anlamını* temsil eden bir sayı dizisine çevrilmiş hâlde saklanıyor. Soru geldiğinde o da sayıya çevriliyor ve en yakın parçalar bulunuyor.

Kelime eşleşmesi aranmıyor: müşteri "param geri gelir mi?" dese, içinde "iade" geçen parçalar yine bulunuyor. Modele sadece **en alakalı 3–6 parça** gidiyor.

| | ESKİ · HER MESAJDA | YENİ · SORUYA GÖRE |
|---|---|---|
| Gönderilen bilgi miktarı | ~~4.180~~ | **~1.610** |
| Gönderilen bilgi parçası | ~~tümü~~ | **3–6** |

*Ölçü birimi "token" — kabaca dört harfe denk gelen, maliyet ve hızı belirleyen birim.*

Ölçeklenme avantajı da var: bilgi tabanı büyüdükçe eski sistem yavaşlar ve pahalılaşırdı. Yeni sistemde 2.000 parça da olsa modele giden miktar sabit kalıyor.

## Birden fazla konu içeren sorular

*Soru iki ayrı konuya değiniyorsa tek arama yetmiyor.*

Anlam bazlı aramanın zayıflığı şu: soru iki konuya birden değiniyorsa arama ağır basan tarafa kayıyor, diğeri boşta kalıyor.

Bu yüzden sistem önce soruyu inceliyor. Birden fazla ayrı bilgi gerekiyorsa soruyu **alt sorulara bölüyor**, her biri için ayrı arama yapıyor. Aramalar aynı anda çalışıyor, sonuçlar birleştirilip tekrarlar ayıklanıyor.

> **MÜŞTERİ:** Platin bir alyans istiyorum, rose gold renginde, dışına da gravür olsun. Yapabilir misiniz?
>
> **SİSTEM BUNU İKİYE BÖLÜYOR:**
> - Platin alyanslar hangi renklerde mevcut?
> - Alyanslarda dış gravür kuralları ve ücreti nedir?

Bu iki bilgi bilgi tabanında bambaşka yerlerde duruyor. Bölme olmasaydı sistem muhtemelen sadece gravür kısmını bulur, platin renk kısıtını kaçırırdı — ve cevap yanlış olurdu, çünkü platin yalnızca beyaz renkte üretiliyor.

Her uzun soru bölünmüyor. "Gravürlü bir yüzüğü, etiketini çıkardıktan sonra 20 gün içinde iade edersem ne öderim?" sorusu üç koşul içeriyor ama hepsi *aynı* politikayı ilgilendirdiği için tek arama yapılıyor. Ayrım: farklı konular mı, aynı konunun farklı koşulları mı?

## Nasıl cevap veriyor

*Gerçek sistemden alınmış bir örnek.*

> **MÜŞTERİ:** 20 gün önce aldığım yüzüğü iade edebilir miyim? Etiketi çıkardım ve üzerinde gravür var.
>
> **ASİSTAN:** Evet, 30 günlük iade süresi içinde olduğunuz için iadeniz işleme alınabilir. Ancak güvenlik etiketi çıkarıldığı ve yüzükte gravür bulunduğu için %20 stok yenileme ücreti, 30 dolar kargo ücreti ve 40 dolar gravür silme ücreti uygulanacaktır.

Bu cevaptaki üç koşul — 20 gün, etiket yok, gravür var — bilgi tabanında *ayrı ayrı* yerlerde duruyor. Sistem üçünü birleştirip doğru ücretleri hesaplıyor. 15 günden önce olsaydı %10 diyecekti; %20 demesi tarihi doğru okuduğunu gösteriyor.

**Ürün sorusu geldiğinde**

> **MÜŞTERİ:** 300 doların altında isim kolyeleri gösterir misiniz?
>
> **ASİSTAN:** İşte 300 doların altındaki isim kolyelerimizden birkaçı:
> - Cursive Vertical Name Necklace — $191
> - Bubble Name Necklace — $205
>
> Ayrıca 300 dolar altı hediye koleksiyonumuzun tamamına göz atabilirsiniz.

Bu ürünler ve fiyatlar o an mağazadan çekildi. Bütçeye uymayan bir ürün (listede $359'luk bir parça vardı) otomatik olarak elendi. Linkler de mağazanın kendi kayıtlarından geliyor — tahmin edilmiyor.

## Eski sistemde neler yanlıştı

*Zoho üzerindeki kurulumun üç ciddi sorunu daha vardı.*

**Ürün linkleri kırıktı**
Eski sistem ürün sayfası adresini ürün adından *tahmin ediyordu*. "4mm Classic Flat Wedding Band" için üretilen adres `4mm-classic-flat-wedding-band` oluyordu; mağazadaki gerçek adres ise `4mm-classic-flat-womens-wedding-ring`. Müşteri linke tıkladığında hata sayfası görüyordu.
→ Artık adres doğrudan mağazadan alınıyor.

**Katalogun %95'i görünmüyordu**
Ürün önerisi yapılırken mağazadan yalnızca ilk 100 ürün çekiliyordu. Mağazada 2.057 aktif ürün var. Yani müşterinin aradığı şey 101. sıradaysa sistem onu hiç göremiyordu.
→ Artık tüm katalog aranabiliyor.

**Her soru için tekrar tekrar yapay zekâya soruluyordu**
Bir ürün önerisi hazırlamak için sistem yapay zekâya dört ayrı soru soruyordu: yazım hatası var mı, bu bir öneri isteği mi, hangi ürün kastediliyor, ve son olarak cevabı yaz. Her soru ayrı bir bekleme demekti.
→ Dördü tek soruda birleştirildi.

## Ölçülen fark

*Aynı işi yapan iki sistemin karşılaştırması.*

| | ESKİ · ZOHO DELUGE | YENİ · PYTHON |
|---|---|---|
| Ürün önerisi için yapay zekâ çağrısı | ~~4~~ | **1** |
| Ürün önerisi için mağaza sorgusu | ~~3–4~~ | **2** |
| Ağırlık sorusu için yapay zekâ çağrısı | ~~2~~ | **1** |
| Aranabilir ürün sayısı | ~~100~~ | **2.057** |
| Ürün linkleri | ~~tahmin~~ | **gerçek** |

Sistemin hızı bu sayılardan geliyor. Eski kurulumda her adım sırayla bekliyordu; yenisinde gereksiz adımlar tamamen kalktı, kalanlar da mümkün olduğunca aynı anda çalışıyor.

- **2,5 sn** — Ortalama cevap süresi
- **96/96** — Sohbet testi başarısı
- **26/27** — Politika testi başarısı

## En büyük bulgu

*Sorun sanılan yerde değildi.*

Sistem bazı sorularda yanlış cevap veriyordu. İlk teşhis "kullanılan yapay zekâ modeli yetersiz" yönündeydi ve daha güçlü bir model denenmesi öneriliyordu.

Asıl sebep bilgi tabanının hazırlanışındaydı. Şirketin 171 dokümanlık bilgisi parçalara bölünürken doküman sınırları gözetilmemişti: bir parça hem iade politikasının sonunu hem de gravür kurallarının başını içerebiliyordu. **174 parçanın 49'u böyle karışıktı.**

Sistem doğru parçayı buluyordu ama parçanın içinde üç ayrı konu olduğu için model hangisinin cevap olduğunu ayırt edemiyordu.

| BÖLME | DÜZELTİLMEDEN | SONRA |
|---|---|---|
| Karışık içerikli bilgi parçası | 49 | **1** |
| Zor senaryolarda doğru cevap | %25 | **%100** |

Bu düzeltmeden sonra daha güçlü modele geçmeye gerek kalmadı. Aksine: ölçüm, hızlı ve ucuz modelin ağır modelden *daha doğru* cevap verdiğini gösterdi. Ağır model hem 7 kat yavaştı hem de daha çok hata yapıyordu.

Buradan çıkan ders şuydu: bir sistemin çıktısını iyileştirmeye çalışmadan önce girdisinin doğru olduğundan emin ol.

## Neden ölçüm

Yapay zekâ sistemlerinde aynı soru iki kez sorulduğunda iki farklı cevap gelebiliyor. Bu yüzden "denedim, çalışıyor" demek yeterli değil.

Her değişiklik 39 farklı senaryo üzerinde, her senaryo 8 kez tekrarlanarak test edildi. Bu yaklaşım birkaç kez yanlış kararı önledi: tek denemede "işe yarıyor" görünen üç ayrı fikir, tekrarlı ölçümde çürüdü ve uygulanmadı.

- Daha güçlü modele geçmek — ölçüldü, daha kötü çıktı
- Cevapları daha tutarlı hale getirmek için ayar değişikliği — ölçüldü, fark etmedi
- Ek bir sıralama katmanı eklemek — kök sebep düzeltilince gereksiz kaldı

Üçü de uygulanmadı. Her biri sisteme karmaşıklık ve maliyet ekleyecekti, karşılığında bir şey kazandırmadan.

## Kullanılan teknolojiler

- **Python & FastAPI** — sistemin çalıştığı altyapı. Eski sistemin aksine adımlar birbirini beklemek zorunda değil; bağımsız işler aynı anda yürüyor.
- **Google Gemini** — soruyu anlama ve cevap yazma. İki farklı boyutta model kullanılıyor: soruyu çözümleyen küçük ve hızlı olan, cevabı yazan ise ölçümle seçilmiş olan.
- **Supabase (pgvector)** — bilgi parçalarının anlamlarıyla birlikte saklandığı veritabanı. Anlam bazlı aramayı bu yapıyor.
- **Shopify Admin API** — canlı ürün, fiyat, sayfa adresi ve ağırlık verisi. Tek sorguda hepsi geliyor.
- **Google Cloud Run** — sistemin yayında durduğu sunucu. Kullanım arttığında kendini büyütüyor, boşta kaldığında ücret işlemiyor.

---

Hazırlayan **Ali Bacık** · Eternate — Renny New York Inc. · Ağustos 2026
