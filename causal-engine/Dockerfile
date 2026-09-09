FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY causal_engine ./causal_engine
EXPOSE 8000
CMD ["uvicorn", "causal_engine.main:app", "--host", "0.0.0.0", "--port", "8000"]
