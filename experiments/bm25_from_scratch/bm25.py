import math

from collections import Counter

import re 

DOCUMENTS = [
    {
        "id": "platinum-colours",
        "text": "Platinum rings are available only in white.",
    },
    {
        "id": "gold-colours",
        "text": "Gold jewelry is available in yellow, rose and white.",
    },
    {
        "id": "engraved-returns",
        "text": "Engraved rings can be returned with an engraving removal fee.",
    },
    {
        "id": "return-window",
        "text": "Customers have 30 days from delivery to return or exchange items.",
    },
    {
        "id": "ring-size-guide",
        "text": "Use the ring size guide to measure your ring size at home.",
    },
]


def tokenize(text):
    
    text = text.lower()
    
    tokens = re.findall(r"\b\w+\b",text)
    
    return tokens


def build_bm25_index(documents):
    
    tokenized_documents = []
    
    document_frequency = Counter()
    
    for document in documents:
        
        tokens = tokenize(document["text"])
        
        tokenized_documents.append(
            {
                "id":document["id"],
                "tokens":tokens,
                "content" : document["text"],
            }
        )
        
        unique_terms = set(tokens)
        
        for term in unique_terms:
            document_frequency[term] += 1
            
        
    total_document_length = sum(
        len(document["tokens"])
        for document in tokenized_documents
    )
    
    average_document_length = (
        total_document_length/ len(tokenized_documents)
    )
    
    return tokenized_documents,document_frequency,average_document_length


def bm25_score(
    query_tokens,
    document_tokens,
    document_frequency,
    document_count,
    average_document_length,
    k1=1.5,
    b=0.75,
):
    
    term_frequency = Counter(document_tokens)
    
    score=0.0
    
    for term in set(query_tokens):
        
        if term not in term_frequency:
            continue
        
        df = document_frequency[term]
        
        idf = math.log(
            1+(document_count-df+0.5)/(df+0.5)
        )
        
        tf=term_frequency[term]
        
        document_length=len(document_tokens)
        
        denominator = (
            tf 
            + k1* (
                1
                -b
                +b * document_length/average_document_length
            )
        )
        
        score += idf * (tf*(k1+1))/denominator
        
        
    return score

def search(query , tokenized_documents, document_frequency, average_document_length):
    
    query_tokens = tokenize(query)
    
    scored_documents = []
    
    for document in tokenized_documents:
        
        score = bm25_score(query_tokens=query_tokens,
                           document_tokens=document["tokens"],
                           document_frequency=document_frequency,
                           document_count=len(tokenized_documents),
                           average_document_length=average_document_length,
                           )
        
        scored_documents.append(
            {
                "id" : document["id"],
                "score" : score,
                "content" : document["content"],
            }
        )
        
    ranked_documents = sorted(
        scored_documents,
        key=lambda document: document["score"],
        reverse=True,
    )
    
    return ranked_documents


if __name__ == "__main__":
    
    
    tokenized_documents, document_frequency, average_document_length = (build_bm25_index(DOCUMENTS))

    query ="platinum white ring"

    results = search (query,tokenized_documents,document_frequency,average_document_length)

    print(f"Query: {query}")

    for index, result in enumerate(results, start=1):

     print(f"{index}. {result['id']} | score={result['score']:.4f}")