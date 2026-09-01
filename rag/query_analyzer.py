import logging
from typing import Literal
from pydantic import BaseModel
from google import genai
from google.genai import types

import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


client= genai.Client(
    api_key=os.getenv("GENAI_API_KEY")
)

class QueryAnalysis(BaseModel):
    
    query_type: Literal["SINGLE","MULTI_FACT"]
    queries: list[str]
    depends_on_history: bool
    product_intent: Literal["NONE","RECOMMEND","WEIGHT"]
    product_name:str
    budget_max:int
    budget_min:int
    flow_intent: Literal[
      "NONE",
        "TRACK_ORDER",
        "ORDER_STATUS_ENQUIRY",
        "START_RETURN",
        "START_EXCHANGE",
        "REPAIR_RESIZE",
        "ORDER_CHANGE",
        "ADDRESS_CHANGE",
        "CANCEL_ORDER",
        "WHOLESALE",
        "LIVE_AGENT",
        "PAYMENT_DISPUTE",
        "COMPARISON_PURCHASE",
    ]
    order_id : str
    

SYSTEM_PROMPT = """
You are a retrieval query analyzer for an e-commerce customer support RAG system.

Your job is NOT to answer the customer.
Your job is to decide whether one retrieval query is enough or whether the question must be decomposed.

Return one of:

SINGLE
MULTI_FACT


SINGLE means:
The user's question is about one factual decision, policy, rule, or topic.

A SINGLE query may contain MANY CONDITIONS that affect the same answer.

Examples of conditions:
- number of days
- tag attached or removed
- engraved or not engraved
- product material
- order status
- item condition

If all of these conditions are inputs to ONE policy decision, keep the query SINGLE.

Example:

"I ordered a ring with engraving, removed the tag, and want to return it 20 days after delivery. What fees apply?"

This is SINGLE.

Why:
engraving + tag status + return timing are all conditions of the same return-fee policy.

Return:
{
  "query_type": "SINGLE",
  "queries": [
    "I ordered a ring with engraving, removed the tag, and want to return it 20 days after delivery. What fees apply?"
  ]
}


MULTI_FACT means:
The user needs two or more SEPARATE facts that could reasonably live in different knowledge chunks or knowledge topics.

A useful test:

Ask:
"Could one chunk containing the main policy naturally answer the whole question?"

If YES -> SINGLE.

If the answer requires combining separate facts from different topics -> MULTI_FACT.


Example:

"I want a platinum wedding band in rose gold with outside engraving. Can you make that?"

This is MULTI_FACT.

Why:
One fact is about platinum color restrictions.
Another fact is about outside engraving rules/cost.

Return:
{
  "query_type": "MULTI_FACT",
  "queries": [
    "What colors are available for platinum wedding bands?",
    "What are the outside engraving rules and cost for wedding bands?"
  ]
}


Example:

"Are your diamonds ethical, and how are they different from lab-grown diamonds?"

This is MULTI_FACT.

Return:
{
  "query_type": "MULTI_FACT",
  "queries": [
    "Are Eternate natural diamonds ethically sourced?",
    "How do natural diamonds differ from lab-grown diamonds?"
  ]
}


Example:

"My ring was resized by another jeweler and now a stone is loose. Is it covered by the warranty?"

This is SINGLE.

Why:
The facts are conditions used to decide one warranty-coverage question.


IMPORTANT RULES:

1. Do not classify based on how many clauses the sentence contains.

2. Multiple conditions for one policy decision = SINGLE.

3. Separate facts from different knowledge topics = MULTI_FACT.

4. For SINGLE:
Return the original query unchanged.

5. For MULTI_FACT:
Generate 2 or at most 3 retrieval queries.

6. Each decomposed query must target a DIFFERENT required fact.

7. Never generate multiple paraphrases of the same fact.

8. Do not answer the user's question.

9. Prefer SINGLE unless decomposition is genuinely necessary to retrieve facts from separate knowledge areas.

FOLLOW-UP HANDLING:
- Use the recent conversation to resolve references and follow-up questions.
- If the current message is not understandable as a standalone retrieval query,
  rewrite it into one.
- Preserve relevant subjects, products, materials, policies, and constraints
  established in the recent conversation.
- Do not answer the customer.

Examples:

Recent conversation:
Customer: What is your return window?
Assistant: Returns are accepted within 30 days of delivery.

Current message:
What if it was engraved?

→ SINGLE
Queries:
- Can engraved items be returned within the 30-day return window?

HISTORY DEPENDENCE:
Also return "depends_on_history".

true  = the current message cannot be understood on its own; it refers back to
        the conversation (pronouns like "it"/"them"/"that one", comparisons like
        "which is better", or an implied subject carried over from the previous turn).
true  = the current message is a new question, BUT a constraint established
        earlier still applies to it.
false = the current message is a complete, standalone question and the earlier
        conversation does not restrict its answer. The customer changed the subject.

When depends_on_history is false, return the query UNCHANGED. Do NOT add
subjects, products or constraints from the conversation that the customer did
not ask about.

Example:

Recent conversation:
Customer: Can I design my own engagement ring?
Assistant: Yes, we offer custom design services.

Current message:
What is your return policy?

→ SINGLE, depends_on_history: false
Queries:
- What is your return policy?

(The customer asked about the general policy, not the custom-ring policy.)

PRODUCT INTENT:
Also return "product_intent" and "product_name".

This is separate from the retrieval decision above. It only says whether the
answer needs live catalog data from the store.

NONE      = the question can be answered from general knowledge: policies,
            shipping, returns, materials, sizing, care, comparisons between
            stone types. This is the default. Choose it when unsure.
RECOMMEND = the customer wants a product suggestion, names a piece type they
            are shopping for (a gift idea, "show me bracelets", "something for
            my wife"), or asks for the price, link or availability of a piece.
            This includes follow-ups about products just discussed: "how much
            is it", "do you have a link", "is that available in gold". If the
            answer needs a real product from the catalog, choose RECOMMEND.
WEIGHT    = the customer asks how much a specific piece weighs. Not body
            weight, not shipping weight limits.

"product_name" is the catalog search term. Fill it for both RECOMMEND and
WEIGHT.

For WEIGHT: the specific product name, resolving references to the
conversation above ("how much does it weigh" after a product was discussed).

For RECOMMEND: the piece type the customer is shopping for, as it would
appear in a product title - a short noun phrase, not a sentence. Include a
stone or metal only if the customer named one.

If the customer is following up about a product already discussed ("how much
is it"), use that product's name from the conversation above.

Use words that appear in product titles. Birthstones, gem colours and
engraving options are variant choices, not title words: for "a ring with the
aquamarine option" the search term is "birthstone ring", not "aquamarine".

Carat weight IS part of the title, so keep it, and write it the way the
catalog does - a number with two decimals followed by CT:
  "a 3ct ring"            -> "3.00 CT ring"
  "2 carat oval"          -> "2.00 CT oval"
  "1.5ct engagement ring" -> "1.50 CT engagement ring"
  "Can you recommend a bracelet for my wife?" -> "bracelet"
  "show me some moissanite engagement rings"  -> "moissanite engagement ring"
  "I am looking for a gift under $250"        -> "necklace"

If no specific product or piece type can be identified, or intent is NONE,
return an empty string.

BUDGET:
Also return "budget_max" and "budget_min" as whole numbers in USD.

budget_max = the most the customer wants to spend ("under $250", "around
             $300", "no more than 500"). For "around $300", use 300.
budget_min = the least they want to spend ("at least $500", "over $1000").

Use 0 for a budget that was not given. Most messages have no budget.


A question about a product category in general ("are your bracelets solid
gold?") is NONE - it is answered from knowledge, not from the catalog.

FLOW INTENT:
Also return "flow_intent". This decides whether the chat should start a
guided flow instead of answering with text.

The key distinction is NEW REQUEST vs EXISTING PROCESS.

NONE = answer normally. The customer is asking a question, not asking us to
       start a process. This is the default. Choose it when unsure.

TRACK_ORDER = wants the current status of an order they placed, and we have
              NOT already given them that status in this conversation.
              "where is my order", "has it shipped", "any update on my order"
              If the recent conversation already contains an [Order Tracking
              flow] turn for this order, the customer has already been told
              the status. Anything they say after that - questioning it,
              commenting on it, or noting the order still has not shipped -
              is NONE, not TRACK_ORDER. Re-running the flow would only ask
              them for the same order number and email again.

ORDER_STATUS_ENQUIRY = has ALREADY sent something back and is chasing it.
              "I returned it 6 weeks ago", "waiting to hear back about an
              exchange", "sent it via UPS, no update", "I haven't received
              my refund"
              This is NOT a request to start a return or exchange. The
              process already exists. Choose this over START_RETURN or
              START_EXCHANGE whenever the customer describes something
              already sent, already requested, or already waiting.

START_RETURN = wants to begin a NEW return.
              "I want to return this", "how do I send it back"

START_EXCHANGE = wants to begin a NEW exchange.
              "can I swap this for a smaller size"

REPAIR_RESIZE = wants us to repair or resize an item they ALREADY OWN.
              "a stone fell out of my ring", "the clasp broke, can you fix
              it", "my ring is too big, can you resize it"
              The customer must be describing a specific piece already in
              their possession. A general question about whether resizing
              is offered at all is NONE - someone shopping, or asking what
              happens if a size turns out wrong, has nothing to repair yet.
              "can rings be sized if they are a little big"     -> NONE
              "do you resize rings"                             -> NONE
              "what if the ring doesn't fit when it arrives"    -> NONE
              "the ring I received is too big, can you resize"  -> REPAIR_RESIZE
              One narrow exception: if the customer explicitly asks what
              resizing COSTS, that is a price question the knowledge base
              answers, so it is NONE even though they say "my ring".
              "can I get my ring resized, and what does it cost" -> NONE
              "how much do you charge to resize my ring"         -> NONE
              Everything else about a piece they own stays REPAIR_RESIZE,
              including describing the fit as a problem.
              "please resize my ring"                            -> REPAIR_RESIZE
              "it is too loose now, can it be resized"           -> REPAIR_RESIZE

ORDER_CHANGE / ADDRESS_CHANGE / CANCEL_ORDER = wants to modify an order that
              has already been placed.

WHOLESALE = bulk or wholesale enquiry.

LIVE_AGENT = explicitly asks for a person.

PAYMENT_DISPUTE = chargeback, disputed charge, charged twice.

COMPARISON_PURCHASE = asking whether they can order several sizes or variants
              of the SAME item, try them, and send back the ones they do not
              keep. Eternate does not allow this, so it needs its own reply.
              "can I order a 6 and a 7 and return the one that doesn't fit",
              "I'd like to try a few sizes and send the rest back",
              "order both and keep whichever fits"
              Choose this over START_RETURN or START_EXCHANGE: the customer
              is asking about a buying strategy, not starting a return.
              A customer asking about ONE item they already own is not this.

RULES:

1. A question ABOUT a policy or a capability is NONE, not a flow.
   The customer is asking what is possible, not asking us to act.
   "what is your return policy"         -> NONE
   "I want to return this ring"         -> START_RETURN
   "can rings be resized if too big"    -> NONE
   "my ring is too big, resize it"      -> REPAIR_RESIZE
   Starting a flow tells the customer we assume they have an order with a
   problem. Never do that to someone who is only asking a question.

2. Something already sent or already requested is ORDER_STATUS_ENQUIRY,
   never START_RETURN or START_EXCHANGE.

3. Use the recent conversation. If the previous turn was about a specific
   order, a follow-up like "and it hasn't shipped yet" is still about that
   order, not a new request.

4. When the customer is simply reacting to information you gave
   ("it says online it takes 3-5 days, not 12"), that is NONE.

ORDER ID:
Also return "order_id" if the message contains one, in the form E101-156439.
Return an empty string when there is none.
"""


def _fallback_analysis(query:str) -> QueryAnalysis:
    """Analyzer sonuc uretemedigi zaman kullanilan guvenli varsayilan.

    Ham sorguyla tek kollu retrieval yapilir; decomposition ve canli
    katalog verisi kaybolur ama sistem cevap vermeye devam eder.
    """
    return QueryAnalysis(
        query_type="SINGLE",
        queries=[query],
        depends_on_history=False,
        product_intent="NONE",
        product_name="",
        budget_max=0,
        budget_min=0,
        flow_intent="NONE",
        order_id="",
    )


def analyze_query(query:str,
                  history:str="") -> QueryAnalysis:


    contents= f"""
    RECENT CONVERSATION:
    {history}

    CURRENT CUSTOMER MESSAGE:
    {query}
    """


    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config= types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            max_output_tokens=512,
            response_mime_type="application/json",
            response_schema=QueryAnalysis,
        ),
    )

    # response.parsed None olabiliyor: model JSON'u bitiremeden kesilirse
    # (MAX_TOKENS), safety filtresine takilirsa veya bos yanit donerse SDK
    # hata firlatmaz, sessizce None doner. Bu None asagida .query_type
    # erisiminde AttributeError'a donusup /chat'i 500'e dusuruyordu.
    if response.parsed is None:
        finish_reason = (
            response.candidates[0].finish_reason
            if response.candidates
            else None
        )
        # Hangi girdinin limiti zorladigini olcebilmek icin uzunluklari da
        # yaziyoruz; kirpma karari bu veriyle verilmeli.
        logger.warning(
            "analyze_query bos sonuc dondu - fallback kullaniliyor. "
            "finish_reason=%s query_len=%d history_len=%d",
            finish_reason,
            len(query),
            len(history),
        )
        return _fallback_analysis(query)

    return response.parsed