import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODELS = ROOT / "models"

# Набор данных: real — реальный каталог Максидома (data/real), synthetic — тестовый (data/catalog)
DATASET = os.getenv("RC_DATASET", "real" if (DATA / "real" / "products.json").exists() else "synthetic")
DATA_DIR = DATA / ("real" if DATASET == "real" else "catalog")
GOLD_DIR = DATA / "real" if DATASET == "real" else DATA / "gold"
MODEL_DIR = MODELS / DATASET

CATALOG_PATH = Path(os.getenv("RC_CATALOG", DATA_DIR / "products.json"))
NEW_PRODUCTS_PATH = DATA_DIR / "new_products.json"
GOLD_PATH = GOLD_DIR / "labels.csv"
GOLD_NEW_PATH = GOLD_DIR / "labels_new.csv"
TAXONOMY_PATH = DATA / "taxonomy.yaml"
KNOWLEDGE_DIR = DATA / "knowledge"
BINDINGS_PATH = Path(os.getenv("RC_BINDINGS", DATA / f"bindings_{DATASET}.json"))

EMBED_MODEL = os.getenv("RC_EMBED_MODEL", "intfloat/multilingual-e5-small")
os.environ.setdefault("HF_HOME", str(MODELS / "hf"))

# Локальная LLM в закрытом контуре (Ollama). Если недоступна — сервис работает без неё.
OLLAMA_URL = os.getenv("RC_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("RC_OLLAMA_MODEL", "qwen2.5:7b-instruct")
LLM_ENABLED = os.getenv("RC_LLM", "auto")  # auto | on | off

DEFAULT_REGION_ID = 1
