import re
from concurrent.futures import ThreadPoolExecutor

from rag.shopify import get_product_weight, search_products, search_collections


# Magazanin hazir butce koleksiyonlari. Bunlar gercek koleksiyonlar;
# musterinin butcesi bir basamaga tam uyuyorsa filtre parametresi
# uretmek yerine bunlari kullaniyoruz.
BUDGET_COLLECTIONS = [
    (250, "https://eternate.com/collections/gifts-under-250"),
    (500, "https://eternate.com/collections/gifts-under-500"),
    (1000, "https://eternate.com/collections/gifts-under-1000"),
]

GIFT_COLLECTION = "https://eternate.com/collections/gift-collection"


def build_product_context(analysis) -> str:
    """analyze_query sonucuna gore canli katalog verisi ceker ve prompt'a
    girecek metni uretir. Veri yoksa bos string doner."""

    if analysis.product_intent == "RECOMMEND":
        return _recommend_text(
            analysis.product_name,
            analysis.budget_max,
            analysis.budget_min,
        )

    if analysis.product_intent == "WEIGHT":
        return _weight_text(analysis.product_name)

    return ""


def _budget_link(budget_max: int, budget_min: int) -> str:
    """Butceye uygun koleksiyon linkini uretir. Link her zaman koddan
    gelir; modele URL kurdurmuyoruz."""

    if budget_min > 0:
        if budget_min >= 1000:
            return "https://eternate.com/collections/gifts-over-1000"
        return f"{GIFT_COLLECTION}?filter.v.price.gte={budget_min}"

    if budget_max <= 0:
        return ""

    for limit, url in BUDGET_COLLECTIONS:
        if budget_max == limit:
            return url

    return f"{GIFT_COLLECTION}?filter.v.price.lte={budget_max}"


def _recommend_text(term: str, budget_max: int = 0, budget_min: int = 0) -> str:
    # Urun ve koleksiyon aramasi birbirinden bagimsiz; paralel calistiriyoruz.
    found_collections = []

    if term:
        with ThreadPoolExecutor(max_workers=2) as executor:
            product_job = executor.submit(search_products, term)
            collection_job = executor.submit(search_collections, term, 2)
            products = product_job.result()
            found_collections = collection_job.result()
    else:
        products = []

    # Terim fazla dar olabilir ("cursive name necklace"); son kelime
    # genelde parca tipidir ("necklace"), onunla tekrar dene.
    if not products and term and " " in term:
        products = search_products(term.rsplit(" ", 1)[-1])

    lines = []

    if products:
        # Butce verildiyse uymayan urunleri ele. Shopify'in variants.price
        # filtresi sorguda sessizce yok sayiliyor, bu yuzden burada suzuyoruz.
        if budget_max > 0:
            products = [p for p in products if float(p["price"]) <= budget_max]

        if budget_min > 0:
            products = [p for p in products if float(p["price"]) >= budget_min]

    if products:
        lines.append("Real products currently in the catalog:")
        lines += [
            f"- {p['title']} - ${p['price']} {p['currency']} - {p['url']}"
            for p in products
        ]

    # Butce verildiyse dogru koleksiyon linki; terim varsa ona uyan
    # gercek koleksiyonlar.
    collections = []

    budget_url = _budget_link(budget_max, budget_min)

    if budget_url:
        label = f"under ${budget_max}" if budget_max > 0 else f"over ${budget_min}"
        collections.append(f"- Gifts {label} - {budget_url}")
    elif not products:
        # Musteri urun istiyor ama analyzer arama terimi cikaramadi
        # ("I am looking for gifts" -> product_name bos). Katalog verisi
        # olmadan model hicbir urun/koleksiyon adi veremiyor ve cevap
        # genel tavsiyeye dusuyor. En azindan gercek hediye koleksiyonunu
        # verelim -- eli bos donmekten iyi.
        collections.append(f"- Gift Collection - {GIFT_COLLECTION}")

    for c in found_collections:
        # Butce koleksiyonu zaten yukarida eklendi; "gift" aramasi
        # Gifts Under $1000 gibi alakasiz basamaklari getiriyor.
        if budget_url and "gift" in c["url"].lower():
            continue
        collections.append(
            f"- {c['title']} ({c['product_count']} items) - {c['url']}"
        )

    if collections:
        lines.append("")
        lines.append("Real collections in the store:")
        lines += collections

    if not lines:
        return ""

    lines.append("")

    if products:
        lines.append(
            "Recommend one or two specific products by name with their exact link. "
            "A collection link may follow as an optional extra. Use these links "
            "exactly as written; never build a link yourself and never add a "
            "filter parameter of your own. "
            "These titles do not list variant choices (birthstone, gem colour, "
            "metal, engraving). If the customer asked for one of those, still name "
            "a product above and say the option is chosen on its product page."
        )
    else:
        # Urun listesi bos; modele urun adi uydurtmayalim. Koleksiyon
        # linki gercek, onu verip ne aradigini sormasi yeterli.
        lines.append(
            "No individual products were matched. Point the customer to the "
            "collection link above, using it exactly as written, and invite "
            "them to say what kind of piece or budget they have in mind. "
            "Do not name any specific product."
        )

    return "\n".join(lines)


def _weight_text(product_name: str) -> str:
    if not product_name:
        return ""

    weight = get_product_weight(product_name)

    if weight is None:
        return (
            "No weight data could be found for the product the customer asked "
            "about. Say you do not have the exact weight on hand and offer to "
            "check with the team at service@eternate.com. Never estimate a weight."
        )

    values = [v["value"] for v in weight["variants"]]
    unit = weight["variants"][0]["unit"]

    lines = [
        f"- {v['options']} -> {v['value']} {v['unit']}"
        for v in weight["variants"]
    ]

    return (
        f"Real weight data for \"{weight['title']}\" ({weight['url']}):\n"
        + "\n".join(lines)
        + f"\n\nRange: {min(values)} to {max(values)} {unit}. "
        "If the customer named a specific option, give only that variant's "
        "weight. If they did not, give the range and offer the exact figure "
        "once they choose an option. Do not list every variant."
    )


def verify_links(answer: str, product_data: str) -> str:
    """Cevaptaki urun linklerini katalog verisiyle dogrular.

    Model bazen handle'i "duzeltmeye" calisiyor -- basliktaki kelimeleri
    link'e ekleyip 404 uretiyor (orn. .../4-prong-solitaire-... yerine
    .../4-prong-solitaire-round-cut-...). Prompt kurali bunu tam
    engellemedi, bu yuzden burada deterministik olarak duzeltiyoruz.
    """
    if not product_data:
        return answer

    valid = set(re.findall(r"https://eternate\.com/products/[^\s)\]]+", product_data))

    if not valid:
        return answer

    # handle -> gecerli URL (uydurma linki dogrusuna esleyebilmek icin)
    by_tail = {}

    for url in valid:
        handle = url.rsplit("/", 1)[-1]
        by_tail[handle] = url

    def fix(match):
        url = match.group(0)

        if url in valid:
            return url

        handle = url.rsplit("/", 1)[-1]

        # Uydurma handle genelde gercek olanin genisletilmis hali; ortak
        # parcalari en cok orten gecerli linki bul.
        parts = set(handle.split("-"))
        best, best_score = None, 0

        for candidate_handle, candidate_url in by_tail.items():
            score = len(parts & set(candidate_handle.split("-")))
            if score > best_score:
                best, best_score = candidate_url, score

        # Yeterince ortusmuyorsa linki tamamen kaldirmak yerine
        # koleksiyona dusurmek daha guvenli degil; bu durumda gercek
        # bir eslesme yoksa ilk gecerli linki kullanmiyoruz.
        return best if best and best_score >= 3 else url

    return re.sub(r"https://eternate\.com/products/[^\s)\]]+", fix, answer)
