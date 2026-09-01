import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from rag.system_prompt_chat_bot import SYSTEM_PROMPT

load_dotenv()


client = genai.Client(
    api_key=os.getenv("GENAI_API_KEY")
)


def generate_answer(
    query:str, 
    contexts: list[dict],
    history:str="",
    product_data:str=""
    ) -> str:
    
    context_text="\n\n---\n\n".join(
        item["content"]
        for item in contexts
    )
    
    catalog_block=""
    
    if product_data:
        catalog_block=f"""
        LIVE CATALOG DATA:
        {product_data}
        """
        
    
    prompt = f"""
    
    KNOWLEDGE CONTEXT:
    {context_text}
    {catalog_block}
    
    RECENT CONVERSATION
    {history}
    
    CURRENT CUSTOMER MESSAGE:  
    {query}
    
    Answer the customer's current message using the knowledge context above.
    Use the conversation history only to understand follow-ups and references.
    """
    
    response=client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
        ),
    )
    
    return response.text
    