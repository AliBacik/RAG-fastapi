import os

from dotenv import load_dotenv
from google import genai
from supabase import create_client


load_dotenv()


gemini_client = genai.Client(
    api_key=os.getenv("GENAI_API_KEY")
)

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)


def retrieve(query: str, match_count: int = 5):

    embedding_response = gemini_client.models.embed_content(
        model="gemini-embedding-2",
        contents=query,
        config={
            "output_dimensionality": 768
        }
    )

    query_embedding = embedding_response.embeddings[0].values

    response = (
        supabase
        .schema("eternate")
        .rpc(
            "match_knowledge_chunks",
            {
                "query_embedding": query_embedding,
                "match_count": match_count
            }
        )
        .execute()
    )

    return response.data