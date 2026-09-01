from typing import Optional

from pydantic import BaseModel

class IntentEventRequest(BaseModel):
    source_message_id: str
    ticket_id: str
    customer_message:str
    gemini_intent: str
    department_name:str

class ChatRequest(BaseModel):
    query:str
    history:str =""
    # Zoho tarafindaki gecikmeyi olcmek icin: Deluge, RAG oncesi
    # harcadigi sureyi ve kendi saatini gonderiyor. Cloud Run loguna
    # yazilinca hangi katmanin yavas oldugu gorunuyor.
    client_pre_ms:int = 0
    client_clock:int = 0
    client_handler:str = ""

class ChatResponse(BaseModel):
    message:str
    flow_intent:str="NONE"
    order_id:str=""
    needs_agent:bool = False

class Order(BaseModel):
    order_number: Optional[str] = None
    financial_status: Optional[str] = None
    fulfillment_status: Optional[str] = None
    created_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancel_reason: Optional[str] = None
    refunds: Optional[list] = None
    tracking_number: Optional[str] = None


class OrderData(BaseModel):
    found: Optional[bool] = None
    orders: Optional[list[Order]] = None


class GenerateReplyRequest(BaseModel):
    ticket_id: Optional[str] = None
    ticket_number: Optional[str] = None
    ticket_status: Optional[str] = None
    ticket_priority: Optional[str] = None
    ticket_channel: Optional[str] = None
    ticket_created_time: Optional[str] = None

    customer_name: Optional[str] = None
    customer_email: Optional[str] = None

    subject: Optional[str] = None
    department: Optional[str] = None
    customer_message: str

    latest_thread_id: Optional[str] = None
    latest_thread_direction: Optional[str] = None
    latest_thread_channel: Optional[str] = None
    latest_thread_from_email: Optional[str] = None
    latest_thread_created_time: Optional[str] = None

    order_data: Optional[OrderData] = None


class GenerateReplyResponse(BaseModel):
    success: bool
    reply: Optional[str] = None
    error: Optional[str] = None
