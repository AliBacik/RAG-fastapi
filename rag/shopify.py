import logging
import os

import requests

from dotenv import load_dotenv

load_dotenv()

SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

GRAPHQL_URL = f"https://{SHOPIFY_STORE}/admin/api/2024-01/graphql.json"

HEADERS={
    "X-Shopify-Access-Token": ADMIN_API_KEY,
    "Content-Type":"application/json",
}

TIMEOUT=10


# Env eksikse istekler sessizce basarisiz olurdu (_graphql hatalari yutuyor):
# Shopify hic calismaz ama kimse fark etmez. Cloud Run'da .env yok, bu
# degiskenler deploy sirasinda gecilmeli.
if not SHOPIFY_STORE or not ADMIN_API_KEY:
    logging.getLogger(__name__).warning(
        "SHOPIFY_STORE veya ADMIN_API_KEY tanimli degil - canli katalog "
        "verisi (urun onerisi, agirlik) devre disi kalacak."
    )

def _graphql(query:str , variables: dict)->dict:
    
    try:
        response = requests.post(
            GRAPHQL_URL,
            json={"query":query,"variables":variables},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return {}
    
    
    if payload.get("errors"):
        return {}
    
    return payload.get("data") or {}


SEARCH_QUERY ="""
query($search:String!,$limit:Int!){
    products(first:$limit,query:$search){
        nodes{
            title
            handle
            priceRangeV2{
                minVariantPrice{amount currencyCode}
            }
        }
    }
}
"""

def search_products(term:str,limit:int=5) -> list[dict]:
    """Baslikta arama yapar. 2057 aktif urun var; REST products.json
    sayfalama gerektirdigi icin GraphQL kullaniyoruz."""
    term = term.replace('"', "").strip()
    
    if not term:
        return[]
    
    data = _graphql(
        SEARCH_QUERY,
        {
            "search" : f"title:*{term}* AND status:active",
            "limit":limit,
        },
    )
    
    products=[]
    
    for node in data.get("products",{}).get("nodes",[]):
        price=node["priceRangeV2"]["minVariantPrice"]
        
        products.append({
            "title":node["title"],
            "url":f"https://eternate.com/products/{node['handle']}",
            "price": price["amount"],
            "currency": price["currencyCode"],
        })
    
    return products


WEIGHT_QUERY="""
query($search:String!){
    products(first:3,query:$search){
        nodes{
            title
            handle
            variants(first:50){
                nodes{
                    selectedOptions{name value}
                    inventoryItem{
                        measurement{
                            weight{
                                value unit
                            }
                        }
                    }
                }
            }
        }
    }
}
"""

def get_product_weight(product_name:str) -> dict | None:
    product_name = product_name.replace('"',"").strip()
    
    if not product_name:
        return None
    
    data = _graphql(
        WEIGHT_QUERY,
        {"search":f"title:*{product_name}* AND status:active"},
    )
    
    nodes = data.get("products",{}).get("nodes",[])
    
    if not nodes:
        return None
    
    matched = nodes[0]
    
    for node in nodes:
        
        if node["title"].lower()==product_name.lower():
            matched=node
            break
        
    
    variants=[]
    
    for variant in matched["variants"]["nodes"]:
        measurement = (variant.get("inventoryItem") or {}).get("measurement") or {}
        weight=measurement.get("weight")
        
        if not weight:
            continue
        
        options = " ".join(
            f"{option['name']}:{option['value']}"
            for option in variant["selectedOptions"]
        )
        
        variants.append({
            "options":options,
            "value": weight["value"],
            "unit" : weight["unit"].lower(),
        })
        
    if not variants:
        return None
    
    return {
        "title" : matched["title"],
        "url" : f"https://eternate.com/products/{matched['handle']}",
        "variants" : variants,
    }
        

COLLECTION_QUERY = """
query($search:String!,$limit:Int!){
    collections(first:$limit,query:$search){
        nodes{
            title
            handle
            productsCount{count}
        }
    }
}
"""

def search_collections(term: str, limit: int = 5) -> list[dict]:
    """Koleksiyon basliginda arama. Magaza kendi kuratorlugunu yapmis
    (Gifts Under $250, Gifts For Mom, Mother's Day Collection gibi),
    bu yuzden hazir koleksiyon varsa filtre parametresi uydurmaktan iyi."""
    term = term.replace('"', "").strip()

    if not term:
        return []

    data = _graphql(
        COLLECTION_QUERY,
        {"search": f"title:*{term}*", "limit": limit},
    )

    return [
        {
            "title": node["title"],
            "url": f"https://eternate.com/collections/{node['handle']}",
            "product_count": node["productsCount"]["count"],
        }
        for node in data.get("collections", {}).get("nodes", [])
    ]