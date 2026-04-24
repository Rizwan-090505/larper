from functools import lru_cache


@lru_cache(maxsize=1)
def _get_model(model_name: str):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name)
