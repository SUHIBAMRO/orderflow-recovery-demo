FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home orderflow
COPY --chown=10001:10001 orderflow ./orderflow
COPY --chown=10001:10001 web ./web
USER 10001
EXPOSE 8080
CMD ["uvicorn", "orderflow.api:app", "--host", "0.0.0.0", "--port", "8080"]
