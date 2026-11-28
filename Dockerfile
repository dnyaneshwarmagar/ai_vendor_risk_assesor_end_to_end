FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi "uvicorn[standard]" streamlit redis rq "psycopg[binary]" \
       langgraph-checkpoint-sqlite httpx
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
