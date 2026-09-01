# JSONL eval vakalarını okuyabilmek için kullanıyoruz.
import json

# Her retriever'ın süresini ölçmek için kullanıyoruz.
import time

# Proje kök dizinine ulaşmak için kullanıyoruz.
from pathlib import Path

# Python'ın import arama yoluna proje kökünü eklemek için kullanıyoruz.
import sys

# Yüklediğimiz gerçek BM25 kütüphanesini import ediyoruz.
import bm25s


# Bu dosyanın iki üst klasörü proje kök dizinidir.
ROOT = Path(__file__).resolve().parents[2]

# rag klasörünü import edebilmek için proje kökünü import yoluna ekliyoruz.
sys.path.insert(0, str(ROOT))


# Production'daki aynı routing mantığını kullanıyoruz.
from rag.adaptive_retriever import adaptive_retrieve

# Vector ve bm25s aynı analyzer kararını kullansın diye import ediyoruz.
from rag.query_analyzer import analyze_query

# Mevcut dense vector retrieval ve Supabase client'ını import ediyoruz.
from rag.retriever import retrieve, supabase


# Bu fonksiyon gerçek knowledge chunk'larını Supabase'den yalnızca okur.
def load_knowledge_chunks():

    # knowledge_chunks tablosundan id ve content alanlarını istiyoruz.
    response = (
        supabase
        .schema("eternate")
        .table("knowledge_chunks")
        .select("id,content")
        .execute()
    )

    # Her Supabase satırını bm25s'nin geri döndürebileceği metadata sözlüğüne çeviriyoruz.
    corpus = [
        {
            # Chunk id'sini saklıyoruz.
            "id": str(row["id"]),

            # bm25s ile indexlenecek chunk metnini saklıyoruz.
            "content": row["content"],
        }
        for row in response.data
    ]

    # Hazırladığımız gerçek corpus'u geri veriyoruz.
    return corpus


# Bu fonksiyon mevcut retrieval eval vakalarını yükler.
def load_cases():

    # Mevcut JSONL eval dosyasının yolunu tanımlıyoruz.
    case_file = ROOT / "evals" / "cases.jsonl"

    # Dosyayı UTF-8 metin olarak okuyoruz.
    file_text = case_file.read_text(encoding="utf-8")

    # Her boş olmayan satırı JSON'dan Python sözlüğüne çeviriyoruz.
    cases = [
        json.loads(line)
        for line in file_text.splitlines()
        if line.strip()
    ]

    # Test vakalarını geri veriyoruz.
    return cases


# Bu fonksiyon bir expected group'un tek bir retrieved chunk içinde olup olmadığını kontrol eder.
def group_found(group, results):

    # Her sonucu tek tek kontrol ediyoruz.
    for result in results:

        # Harf farkını önemsiz yapmak için chunk metnini küçültüyoruz.
        content = result["content"].lower()

        # Bu chunk'ın gruptaki tüm kelimeleri içerdiğini başlangıçta varsayıyoruz.
        all_terms_found = True

        # Örneğin ["platinum", "white"] içindeki her kelimeyi kontrol ediyoruz.
        for term in group:

            # Bir kelime yoksa bu chunk grup için başarısızdır.
            if term.lower() not in content:
                all_terms_found = False

                # Bu chunk için daha fazla kontrol yapmaya gerek yoktur.
                break

        # Tüm kelimeler aynı chunk içinde bulunduysa başarıyla dönüyoruz.
        if all_terms_found:
            return True

    # Hiçbir sonuç chunk'ı grubu tam içermiyorsa başarısız dönüyoruz.
    return False


# Bu fonksiyon bir test vakanın bütün expected group'larını kontrol eder.
def retrieval_passes(case, results):

    # Her beklenen bilgi grubunu sırayla kontrol ediyoruz.
    for group in case["expected_groups"]:

        # Bir grup bile bulunamazsa vaka başarısızdır.
        if not group_found(group, results):
            return False

    # Tüm gruplar bulunduysa vaka başarılıdır.
    return True


# Bu fonksiyon bm25s sonuçlarını production adaptive retriever'ın beklediği formata çevirir.
def bm25s_retrieve(query, match_count=5):

    # Sorguyu bm25s'nin kullandığı token formatına çeviriyoruz.
    query_tokens = bm25s.tokenize(query, stopwords="en")

    # Index'ten en iyi match_count kadar dokümanı ve skorlarını istiyoruz.
    documents, scores = bm25s_retriever.retrieve(
        query_tokens,
        k=match_count,
    )

    # bm25s ilk eksende sorguları tutar; tek sorgumuz olduğu için [0] kullanıyoruz.
    top_documents = documents[0]

    # Skorların da tek sorguya ait ilk satırını alıyoruz.
    top_scores = scores[0]

    # bm25s metadata sözlüklerini production retriever formatına çeviriyoruz.
    formatted_results = []

    # Doküman ve skorları aynı sırayla birlikte geziyoruz.
    for document, score in zip(top_documents, top_scores):

        # Adaptive retriever'ın anlayacağı tek sonucu oluşturuyoruz.
        formatted_results.append(
            {
                # Gerçek chunk id'sini koruyoruz.
                "id": document["id"],

                # Eval'in kelime kontrolü yapabilmesi için content'i koruyoruz.
                "content": document["content"],

                # Adaptive retriever skor alanını similarity adıyla bekler.
                # Bu cosine similarity değil; bm25s lexical skorudur.
                "similarity": float(score),
            }
        )

    # Formatlanmış BM25S sonuçlarını geri veriyoruz.
    return formatted_results


# Bu fonksiyon bir yöntemin ilk üç sonucunu okunur biçimde gösterir.
def print_top_results(label, results):

    # Hangi retrieval yöntemini yazdığımızı gösteriyoruz.
    print(f"  {label} top results:")

    # İlk üç sonucu sıra numarasıyla geziyoruz.
    for index, result in enumerate(results[:3], start=1):

        # Chunk'ı tek satıra çevirip kısa önizleme alıyoruz.
        preview = " ".join(result["content"].split())[:100]

        # Skoru ve önizlemeyi yazıyoruz.
        print(f"    {index}. score={result['similarity']:.4f} | {preview}")


# Gerçek 241 knowledge chunk'ını Supabase'den yüklüyoruz.
corpus = load_knowledge_chunks()

# bm25s'ye yalnız metin listesini vererek tokenization yapıyoruz.
corpus_tokens = bm25s.tokenize(
    [document["content"] for document in corpus],
    stopwords="en",
)

# bm25s'ye orijinal metadata corpus'unu veriyoruz; retrieve çağrısı id/content sözlüğünü döndürür.
bm25s_retriever = bm25s.BM25(corpus=corpus)

# Tokenize edilmiş gerçek corpus üzerinde BM25S index'ini oluşturuyoruz.
bm25s_retriever.index(corpus_tokens)

# Mevcut eval vakalarını yüklüyoruz.
cases = load_cases()

# Vector retrieval PASS sayacını sıfırdan başlatıyoruz.
vector_passed_count = 0

# BM25S retrieval PASS sayacını sıfırdan başlatıyoruz.
bm25s_passed_count = 0

# Her eval vakasını iki yöntemle karşılaştırıyoruz.
for case in cases:

    # Follow-up vakasında history varsa alıyor, yoksa boş metin kullanıyoruz.
    history = case.get("history", "")

    # Analyzer'ı yalnızca bir kez çağırıyoruz.
    # Böylece iki yöntem aynı routing kararını kullanır.
    analysis = analyze_query(case["query"], history=history)

    # Vector retrieval süresini ölçmek için başlangıç anını kaydediyoruz.
    vector_started_at = time.perf_counter()

    # Mevcut production vector retrieval'ı çalıştırıyoruz.
    vector_results = adaptive_retrieve(
        case["query"],
        retrieve,
        history=history,
        analysis=analysis,
    )

    # Vector retrieval süresini milisaniye olarak hesaplıyoruz.
    vector_ms = (time.perf_counter() - vector_started_at) * 1000

    # BM25S retrieval süresini ölçmek için başlangıç anını kaydediyoruz.
    bm25s_started_at = time.perf_counter()

    # BM25S retrieval'ı aynı route kararıyla çalıştırıyoruz.
    bm25s_results = adaptive_retrieve(
        case["query"],
        bm25s_retrieve,
        history=history,
        analysis=analysis,
    )

    # BM25S retrieval süresini milisaniye olarak hesaplıyoruz.
    bm25s_ms = (time.perf_counter() - bm25s_started_at) * 1000

    # Vector sonuçlarının expected group'ları bulup bulmadığını hesaplıyoruz.
    vector_passed = retrieval_passes(case, vector_results)

    # BM25S sonuçlarının expected group'ları bulup bulmadığını hesaplıyoruz.
    bm25s_passed = retrieval_passes(case, bm25s_results)

    # Vector geçtiyse sayacı artırıyoruz.
    if vector_passed:
        vector_passed_count += 1

    # BM25S geçtiyse sayacı artırıyoruz.
    if bm25s_passed:
        bm25s_passed_count += 1

    # Çalışan test vakanın adını ekrana yazıyoruz.
    print(f"\n--- {case['id']} ---")

    # Ortak analyzer route kararını gösteriyoruz.
    print(f"Route: {analysis.query_type}")

    # Vector PASS/FAIL ve retrieval süresini gösteriyoruz.
    print(f"Vector: {'PASS' if vector_passed else 'FAIL'} | {vector_ms:.0f} ms")

    # BM25S PASS/FAIL ve retrieval süresini gösteriyoruz.
    print(f"BM25S: {'PASS' if bm25s_passed else 'FAIL'} | {bm25s_ms:.0f} ms")

    # Vector'ın ilk üç sonucunu gösteriyoruz.
    print_top_results("Vector", vector_results)

    # BM25S'nin ilk üç sonucunu gösteriyoruz.
    print_top_results("BM25S", bm25s_results)


# Karşılaştırma özetini ekrana yazıyoruz.
print("\n=== BM25S comparison summary ===")

# Vector'ın toplam PASS sayısını yazıyoruz.
print(f"Vector: {vector_passed_count}/{len(cases)} passed")

# BM25S'nin toplam PASS sayısını yazıyoruz.
print(f"BM25S: {bm25s_passed_count}/{len(cases)} passed")