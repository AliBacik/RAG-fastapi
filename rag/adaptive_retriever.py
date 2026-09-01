from concurrent.futures import ThreadPoolExecutor

from rag.query_analyzer import analyze_query
from rag.retriever import retrieve


def adaptive_retrieve(query,retrieve_fn,history="",analysis=None):
    
    if analysis is None:
        analysis=analyze_query(query,history=history)
    
    
    if analysis.query_type=="SINGLE":
        rewritten=analysis.queries[0]

        # Rewrite retrieval'i iyilestirebilir de bozabilir de (ornegin
        # onceki turdaki bir metal/urun adini dusurebilir), bu yuzden
        # ham sorguyu da retrieve edip sonuclari birlestiriyoruz.
        if rewritten.strip().lower()==query.strip().lower():
            return retrieve_fn(query)

        # Soru history'ye bagli degilse (konu degismis) rewrite ham sorguya
        # olmayan bir kisit ekleyebiliyor -- orn. "What is your return policy?"
        # -> "...for custom-designed engagement rings?". Bu durumda rewrite
        # kolunu atliyoruz.
        if not analysis.depends_on_history:
            return retrieve_fn(query)

        # Iki retrieval birbirinden bagimsiz; paralel calistiriyoruz.
        # executor.map girdi sirasini korur, boylece sonuc deterministik kalir.
        return _retrieve_many((rewritten,query),retrieve_fn)

    return _retrieve_many(analysis.queries,retrieve_fn)


def _retrieve_many(queries,retrieve_fn,match_count=3):
    """Sorgulari paralel retrieve edip sirayi koruyarak birlestirir."""
    queries=list(queries)

    with ThreadPoolExecutor(max_workers=len(queries)) as executor:
        batches=executor.map(
            lambda q: retrieve_fn(q,match_count=match_count),
            queries,
        )

        combined=[]

        for used_query,results in zip(queries,batches):
            for result in results:
                result["retrieved_for"]=used_query
                combined.append(result)

    return deduplicate_results(combined)


def deduplicate_results(results):
    
    """Tekrarlari atar ve skora gore siralar.

    Iki retrieval kolu ayri ayri geldigi icin birlesik listede global bir
    sira yok; kol sirasina gore diziliyordu. Skora gore siralamak en
    alakali chunk'i one aliyor.
    """
    
    seen = set()
    unique_results=[]
    
    for result in results:
        content=result["content"]
        
        if content not in seen:
            seen.add(content)
            unique_results.append(result)
            
    
    return sorted(
        unique_results,
        key=lambda r: r["similarity"],
        reverse=True
    )
    
def adaptive_retrieve_overlapped(query,retrieve_fn,history="",analyze_fn=None):
    """adaptive_retrieve ile AYNI sonucu dondurur, ama daha erken baslar.

    Fikir: adaptive_retrieve'in ucu ucuna butun SINGLE yollarinda ham sorgu
    retrieve ediliyor. Ham sorgu musterinin yazdigi metin -- analyzer'in
    cevabina ihtiyaci yok. O yuzden ham retrieval'i analyzer ile AYNI ANDA
    baslatiyoruz.

    Analyzer ~0.91s, ham retrieval ~0.78s. Ham kol analyzer'in golgesinde
    bitiyor, yani bedavaya geliyor. Olculen kazanc:
      - topic shift / rewrite==ham  -> 0.78s (retrieval tamamen bedava)
      - rewrite farkli              -> ~0.4s (ham kol saklandi)

    Cikti adaptive_retrieve ile birebir ayni; sadece cagri sirasi degisti."""
    
    if analyze_fn is None:
        analyze_fn = analyze_query
        
    with ThreadPoolExecutor(max_workers=2) as executer:
        analysis_job = executer.submit(analyze_fn,query,history)

        # Ham kolu analyzer'dan ONCE baslatiyoruz, yani hangi dala
        # girecegimizi henuz bilmiyoruz. Iki dalin ihtiyaci farkli:
        #   tek kol  -> match_count=5 (retrieve varsayilani)
        #   iki kol  -> match_count=3 (_retrieve_many'nin kullandigi)
        # Fazla olani isteyip iki-kol dalinda ilk 3'u aliyoruz; boylece
        # tek cagri her iki dali da karsiliyor.
        raw_job = executer.submit(retrieve_fn,query,match_count=5)

        analysis = analysis_job.result()

        if analysis.query_type =="SINGLE":
            rewritten = analysis.queries[0]

            same_query = rewritten.strip().lower()==query.strip().lower()

            if same_query or not analysis.depends_on_history:
                return raw_job.result(),analysis


            rewritten_results = retrieve_fn(rewritten,match_count=3)
            # _retrieve_many ham kolu da 3 ile cagiriyordu; ayni sayida
            # aday kalsin diye fazlasini kirpiyoruz.
            raw_results = raw_job.result()[:3]

            combined=[]
            
            for used_query, results in ((rewritten,rewritten_results),(query,raw_results)):
                for result in results:
                    result["retrieved_for"] = used_query
                    combined.append(result)
                    
            return deduplicate_results(combined), analysis
        return _retrieve_many(analysis.queries,retrieve_fn),analysis
            
            