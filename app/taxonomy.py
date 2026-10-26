from functools import lru_cache

import yaml

from .config import TAXONOMY_PATH


@lru_cache
def taxonomy() -> dict:
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def work_types() -> list[dict]:
    return taxonomy()["work_types"]


def work_type_ids() -> list[str]:
    return [w["id"] for w in work_types()]


def work_type_name(wid: str) -> str:
    return next((w["name"] for w in work_types() if w["id"] == wid), wid)


def rooms() -> dict:
    return taxonomy()["rooms"]
