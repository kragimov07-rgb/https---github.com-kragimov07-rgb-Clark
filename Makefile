PY ?= .venv/bin/python

setup:            ## окружение и зависимости
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

model:            ## скачать модель эмбеддингов multilingual-e5-small в models/hf (один раз, до ухода в закрытый контур)
	HF_HOME=models/hf $(PY) -c "from sentence_transformers import SentenceTransformer as S; S('intfloat/multilingual-e5-small')"

data:             ## сгенерировать тестовый каталог и эталонную разметку
	$(PY) scripts/generate_catalog.py

train:            ## обучить модель матчинга -> models/matcher.joblib
	$(PY) -m scripts.train

eval:             ## воспроизводимая оценка качества -> reports/metrics.md
	$(PY) -m eval.evaluate

test:
	$(PY) -m pytest -q

licenses:         ## проверка лицензий зависимостей (без GPL/AGPL)
	$(PY) scripts/check_licenses.py

run:
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

all: data train eval test

real-data:        ## реальный каталог Максидома из data/real/raw -> data/real
	$(PY) -m scripts.build_real_catalog

eval-real:        ## оценка на реальном каталоге -> reports/metrics_real.md (~1 ч)
	$(PY) -m eval.evaluate --folds 3 --no-ablation

screenshots:      ## скриншоты UI для презентации (сервис должен быть запущен)
	PLAYWRIGHT_BROWSERS_PATH=.venv/pw $(PY) scripts/screenshots.py

slides:           ## презентация docs/RepairCalc.pptx из актуальных метрик
	$(PY) -m scripts.make_presentation
