FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/models/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY requirements.txt .
# CPU-сборка torch: эмбеддинги e5-small быстро считаются на CPU, GPU оставляем LLM (Ollama)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt
COPY . .
# Модель эмбеддингов кладётся в образ заранее (make model) — в закрытом контуре интернета нет
RUN test -d models/hf || (echo "models/hf отсутствует: выполните 'make model' перед сборкой" && exit 1)
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
