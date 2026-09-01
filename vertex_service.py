import logging
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from prompts import SYSTEM_PROMPT
from schemas import GenerateReplyRequest
from rag.retriever import retrieve
from rag.text_utils import format_value, strip_html
from rag.order_formatter import build_orders_text

load_dotenv()

logger = logging.getLogger("eternate-ai-api")

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us")
TUNED_ENDPOINT = os.getenv("VERTEX_TUNED_ENDPOINT")

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
        )
    return _client


def build_prompt(request: GenerateReplyRequest, orders_text: str, retrieved_policy_text:str) -> str:
    sections = [
        "MATCHED SHOPIFY ORDER DATA",
        "",
        orders_text,
        "",
        "CUSTOMER MESSAGE",
        "",
        strip_html(request.customer_message),
        "",

        "RETRIEVED POLICY TEXT",
        "",
        retrieved_policy_text,
        "",

        "POLICY PRIORITY RULE",
        "",
        "When relevant retrieved policy context is supplied, treat it as the current source of truth.",
        "Do not contradict it or invent policy details that are not supported by it.",
        "",

        "TICKET INFORMATION",
        "",
        f"- Ticket ID: {format_value(request.ticket_id)}",
        f"- Ticket number: {format_value(request.ticket_number)}",
        f"- Subject: {format_value(request.subject)}",
        f"- Status: {format_value(request.ticket_status)}",
        f"- Priority: {format_value(request.ticket_priority)}",
        f"- Channel: {format_value(request.ticket_channel)}",
        f"- Department: {format_value(request.department)}",
        f"- Created time: {format_value(request.ticket_created_time)}",
        "",
        "CUSTOMER INFORMATION",
        "",
        f"- Customer name: {format_value(request.customer_name)}",
        f"- Customer email: {format_value(request.customer_email)}",
        "",
        "LATEST MESSAGE INFORMATION",
        "",
        f"- Thread ID: {format_value(request.latest_thread_id)}",
        f"- Direction: {format_value(request.latest_thread_direction)}",
        f"- Channel: {format_value(request.latest_thread_channel)}",
        f"- Sender email: {format_value(request.latest_thread_from_email)}",
        f"- Created time: {format_value(request.latest_thread_created_time)}",
        "",
        "RETURN AND EXCHANGE PORTAL",
        "",
        "https://eternate.com/pages/return-portal",
        "",
        "ORDER DATA INTERPRETATION RULE",
        "",
        "Use the supplied order data literally.",
        "",
        "Missing, null, empty, or absent values are unknown unless another supplied "
        "field explicitly establishes the fact.",
        "",
        "Never infer an order, shipment, refund, cancellation, payment, production, "
        "or delivery status from the absence of data.",
        "",
        "The only exception is where a field above explicitly states what the "
        "supplied data confirms. Facts stated as confirmed may be used directly.",
        "",
        "INTERNAL ACTION CLAIMS",
        "",
        "Do not claim that the case has been sent, shared, escalated, assigned, or "
        "forwarded to a finance team, support team, production team, or any other "
        "department unless supplied workflow data explicitly confirms that action "
        "occurred.",
        "",
        "Do not say that a requested cancellation will proceed after verification "
        "unless the supplied data confirms that cancellation is still possible.",
        "",
        "Do not state or imply how a duplicate charge will be resolved, whether it "
        "will be refunded, or whether it is part of a cancellation process unless "
        "supplied payment/workflow data explicitly confirms this.",
        "",
        "PAYMENT EVIDENCE REQUESTS",
        "",
        "Do not ask the customer for bank statements, screenshots, or additional "
        "payment evidence unless the supplied data shows that this information is "
        "actually required.",
        "",
        "TASK",
        "",
        "Prepare one customer-facing Eternate email reply draft for the customer "
        "message above.",
        "",
        "The message has already passed an intent-check step and was classified as "
        "not requiring a separate specialized automated workflow.",
        "",
        "However, independently understand the customer's actual request and apply "
        "the relevant Eternate policy from the system instructions.",
        "",
        "Use only:",
        "- the customer message",
        "- supplied ticket information",
        "- supplied customer information",
        "- supplied latest-message information",
        "- supplied normalized Shopify order data",
        "- policies in the system instructions",
        "",
        "Never invent missing information.",
        "",
        "Do not mention the intent-check step.",
        "",
        "Do not mention Zoho Flow, Gemini, automation, prompts, nodes, webhooks, "
        "APIs, or internal workflows.",
        "",
        "Return only the customer-facing email body.",
    ]

    return "\n".join(sections)


def generate_reply(request: GenerateReplyRequest) -> str:
    orders_text = build_orders_text(request)

    retrieval_query = strip_html(request.customer_message)

    try:
        contexts = retrieve(retrieval_query, match_count=3)

        retrieved_policy_text = "\n\n---\n\n".join(
            item["content"]
            for item in contexts
        )
    except Exception:
        logger.exception(
            "RAG retrieval failed for ticket_id=%s",
            request.ticket_id,
        )
        retrieved_policy_text = (
            "No retrieved policy context is available for this request."
        )

    prompt = build_prompt(
        request,
        orders_text,
        retrieved_policy_text,
    )

    response = get_client().models.generate_content(
        model=TUNED_ENDPOINT,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        ),
    )

    return response.text
