import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from schemas import GenerateReplyRequest, GenerateReplyResponse, ChatRequest,ChatResponse , IntentEventRequest
from vertex_service import generate_reply as generate_reply_from_vertex

from rag.query_analyzer import analyze_query
from rag.product_context import build_product_context, verify_links
from rag.retriever import retrieve , supabase
from rag.adaptive_retriever import adaptive_retrieve_overlapped
from rag.generator import generate_answer

import json
import time
import uuid


logger = logging.getLogger("eternate-rag-fastapi")

logger.setLevel(logging.INFO)

if not logger.handlers:
    handler= logging.StreamHandler()
    
    handler.setFormatter(
        logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    
    logger.addHandler(handler)
    
logger.propagate= False

ETERNATE_API_KEY = os.getenv("ETERNATE_API_KEY")

app = FastAPI(title="Eternate RAG API")

@app.middleware("http")
async def log_chat_failures(request: Request, call_next):
    
    started_at = time.perf_counter()
    
    request_id = uuid.uuid4().hex
    
    try:
        response = await call_next(request)
        
    except Exception as exc:
        
        if request.url.path =="/chat":
            
            logger.exception(
                json.dumps(
                    {
                        "event" : "chat_failed",
                        "request_id" : request_id,
                        
                        "error_type" : type(exc).__name__,
                        "total_ms" : round(
                            (time.perf_counter()-started_at)*1000
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        raise
    return response

def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not ETERNATE_API_KEY or x_api_key != ETERNATE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "eternate-rag-fastapi"}

@app.post(
    "/intent-events",
    dependencies=[Depends(verify_api_key)],
)
def save_intent_event(event: IntentEventRequest):
    try:
        supabase.schema("eternate").table("intent_events").upsert(event.model_dump(),
                on_conflict="source_message_id",
                ).execute()
        
        return {"success": True}

    except Exception:
        logger.exception(
         "Intent event save failed for ticket_id=%s", 
            event.ticket_id,  
        )

        raise HTTPException(  
            status_code=500, 
            detail="Intent event could not be saved.",  
        )

@app.post("/generate-reply", response_model=GenerateReplyResponse, dependencies=[Depends(verify_api_key)])
def generate_reply(request: GenerateReplyRequest):
    if not request.customer_message or not request.customer_message.strip():
        raise HTTPException(status_code=422, detail="customer_message is required")

    try:
        reply_text = generate_reply_from_vertex(request)
        return GenerateReplyResponse(success=True, reply=reply_text)
    except Exception:
        logger.exception("Reply generation failed for ticket_id=%s", request.ticket_id)
        return JSONResponse(
            status_code=500,
            content=GenerateReplyResponse(success=False, error="Reply generation failed.").model_dump(),
        )


def _run_retrieval_and_publish_analysis(query,history,analysis_slot):
    """Retrieval'i yurutur, analysis'i hazir olur olmaz disari verir.

    Neden gerekli: Shopify cagrisi analysis'e bagli, ama analysis artik
    retrieval isinin ICINDE uretiliyor. Retrieval'in tamamen bitmesini
    beklersek Shopify'i gec baslatiriz ve paralelligi kaybederiz.
    """
    def analyze_and_publish(q,h):
        try:
            result=analyze_query(q,history=h)
        except BaseException as exc:
            # Hata iletilmezse analysis_slot.result() sonsuza kadar bekler
            # ve istek 120s timeout'a kadar asili kalir.
            analysis_slot.set_exception(exc)
            raise
        analysis_slot.set_result(result)
        return result

    return adaptive_retrieve_overlapped(
        query,retrieve,history,analyze_fn=analyze_and_publish
    )


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
def chat(request: ChatRequest):

    # Bos sorgu embedding API'sine gidince 400 INVALID_ARGUMENT
    # ("content contains an empty Part") firlatiyor ve istek 500'e dusuyordu.
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=422, detail="query is required")
    
    request_id = uuid.uuid4().hex
    started_at = time.perf_counter()

    # Ham retrieval analyzer ile ayni anda basliyor (analyzer'in golgesinde
    # bedavaya geliyor). Shopify ise analysis hazir olur olmaz devreye
    # giriyor -- uc is de birbirinin uzerine biniyor.
    analysis_slot = Future()

    with ThreadPoolExecutor(max_workers=3) as executor:
        retrieval_job = executor.submit(
            _run_retrieval_and_publish_analysis,
            request.query,
            request.history,
            analysis_slot,
        )

        # Analyzer bitene kadar bekliyoruz (~0.9s). Bu sirada ham
        # retrieval zaten calisiyor.
        analysis = analysis_slot.result()
        
        analysis_ready_ms = (time.perf_counter()-started_at)*1000

        # Shopify'i simdi baslat; retrieval hala devam ediyor olabilir.
        product_job = executor.submit(build_product_context, analysis)

        contexts,analysis = retrieval_job.result()
        product_data = product_job.result()
        
        context_ready_ms = (time.perf_counter()-started_at)*1000

    generation_started_at = time.perf_counter()
    
    answer = generate_answer(
        query=request.query,
        contexts=contexts,
        history=request.history,
        product_data=product_data
    )

    # Model bazen urun linkini "duzeltip" 404 uretiyor; katalog verisine
    # gore dogrula.
    answer = verify_links(answer, product_data)
    
    generation_ms = (time.perf_counter()  - generation_started_at)*1000
    
    total_ms = (time.perf_counter()-started_at)*1000
    
    logger.info(
        json.dumps(
            {
                "event" : "chat_completed",
                "request_id" : request_id,
                "query_type" : analysis.query_type,
                "depends_on_history": analysis.depends_on_history,
                "product_intent" : analysis.product_intent,
                "flow_intent":analysis.flow_intent,
                "context_count" : len(contexts),
                "top_similarity":(
                    round(contexts[0]["similarity"],4)
                    if contexts
                    else None
                ),
                "analysis_ready_ms": round(analysis_ready_ms),         
                "context_ready_ms": round(context_ready_ms),
                "generation_ms": round(generation_ms),
                "total_ms": round(total_ms),          
                "transfer_to_agent": "[TRANSFER_TO_AGENT]" in answer,
                # Zoho tarafi: RAG cagrisindan ONCE harcanan sure ve
                # Deluge saati. Toplam gecikmeyi katmanlara ayirmak icin.
                "client_handler": request.client_handler,
                "client_pre_ms": request.client_pre_ms,
                "client_clock": request.client_clock,
            },
            
            ensure_ascii=False,
        )
    )

    return ChatResponse(message=answer,flow_intent=analysis.flow_intent,order_id=analysis.order_id,needs_agent="[TRANSFER_TO_AGENT]" in answer,)