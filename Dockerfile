FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tradebot ./tradebot
RUN useradd --create-home bot && mkdir -p data logs && chown bot data logs
USER bot
ENTRYPOINT ["python", "-m", "tradebot"]
CMD ["paper", "--config", "config.yaml"]
