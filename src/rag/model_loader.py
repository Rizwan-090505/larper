from functools import lru_cache
from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def _get_model(model_name: str):
    return SentenceTransformer(model_name)
