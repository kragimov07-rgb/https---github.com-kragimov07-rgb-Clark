"""Проверка лицензий установленных зависимостей: правила хакатона запрещают «вирусные» лицензии (GPL/AGPL...)."""
import re
import sys
from importlib import metadata
from pathlib import Path

VIRAL = re.compile(r"\b(A?GPL|GNU General Public|Affero|SSPL|EUPL|OSL)\b", re.I)
LGPL = re.compile(r"LGPL|Lesser General Public", re.I)
OK_OVERRIDES = {  # пакеты, у которых метаданные неполные — лицензия проверена вручную
    "torch": "BSD-3-Clause", "numpy": "BSD-3-Clause", "scipy": "BSD-3-Clause", "pyyaml": "MIT",
    "certifi": "MPL-2.0 (слабый copyleft на уровне файла, без изменений не распространяется)",
    "tqdm": "MPL-2.0 AND MIT", "fsspec": "BSD-3-Clause", "networkx": "BSD-3-Clause", "sympy": "BSD",
    "mpmath": "BSD", "jinja2": "BSD-3-Clause", "markupsafe": "BSD-3-Clause", "pillow": "MIT-CMU (HPND)",
    "filelock": "Unlicense", "safetensors": "Apache-2.0", "tokenizers": "Apache-2.0",
    "huggingface-hub": "Apache-2.0", "transformers": "Apache-2.0", "regex": "Apache-2.0",
}


def lic(dist):
    m = dist.metadata
    name = m["Name"].lower()
    if name in OK_OVERRIDES:
        return OK_OVERRIDES[name]
    expr = m.get("License-Expression")
    if expr:
        return expr
    cls = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    if cls:
        return "; ".join(cls)
    raw = (m.get("License") or "").strip().splitlines()
    return raw[0][:80] if raw else "UNKNOWN"


def main():
    rows, bad = [], []
    for d in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = d.metadata["Name"]
        if name.lower() in ("pip", "setuptools", "wheel"):
            continue
        l = lic(d)
        flag = "LGPL (динамическая линковка, допустимо)" if LGPL.search(l) else ("ЗАПРЕЩЕНО" if VIRAL.search(l) else "")
        if flag == "ЗАПРЕЩЕНО":
            bad.append(name)
        rows.append(f"| {name} | {d.version} | {l} | {flag} |")
    md = ["# Лицензии зависимостей", "", "Сгенерировано `make licenses`. Модели: intfloat/multilingual-e5-small — MIT; "
          "Qwen2.5-7B/14B-Instruct (Ollama) — Apache-2.0; Ollama — MIT.", "",
          "| Пакет | Версия | Лицензия | Замечание |", "|---|---|---|---|"] + rows
    Path("docs").mkdir(exist_ok=True)
    Path("docs/licenses.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"пакетов: {len(rows)}; запрещённых: {bad or 'нет'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
