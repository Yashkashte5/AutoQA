import chromadb
import json
from chromadb.utils import embedding_functions

_client = chromadb.PersistentClient(path="./chroma_data")
_ef = embedding_functions.DefaultEmbeddingFunction()


def _flatten_metadata(endpoint: dict) -> dict:
    flat = {}
    for k, v in endpoint.items():
        if isinstance(v, (dict, list)):
            flat[k] = json.dumps(v)
        else:
            flat[k] = v
    return flat


def index_endpoints(suite_id: str, endpoints: list[dict]):
    collection = _client.get_or_create_collection(
        name=f"suite_{suite_id}",
        embedding_function=_ef,
    )
    docs = [f"{e['method']} {e['path']} — {e['summary']}" for e in endpoints]
    ids = [f"{suite_id}_{i}" for i in range(len(endpoints))]
    metadatas = [_flatten_metadata(e) for e in endpoints]
    collection.upsert(documents=docs, ids=ids, metadatas=metadatas)


def retrieve_endpoints(suite_id: str, query: str, n: int = 5) -> list[dict]:
    collection = _client.get_or_create_collection(
        name=f"suite_{suite_id}",
        embedding_function=_ef,
    )
    # Cap n at collection size to avoid ChromaDB errors
    actual_n = min(n, collection.count())
    if actual_n == 0:
        return []
    results = collection.query(query_texts=[query], n_results=actual_n)
    raw = results.get("metadatas", [[]])[0]
    parsed = []
    for item in raw:
        restored = {}
        for k, v in item.items():
            try:
                restored[k] = json.loads(v) if isinstance(v, str) and v.startswith(("{", "[")) else v
            except Exception:
                restored[k] = v
        parsed.append(restored)
    return parsed


def get_collection_size(suite_id: str) -> int:
    """Return the number of indexed endpoints for a given suite."""
    collection = _client.get_or_create_collection(
        name=f"suite_{suite_id}",
        embedding_function=_ef,
    )
    return collection.count()