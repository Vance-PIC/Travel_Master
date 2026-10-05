FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY mcp/requirements.txt /app/mcp/requirements.txt
RUN pip install --no-cache-dir -r /app/mcp/requirements.txt \
    && useradd --create-home --uid 10001 app

COPY mcp/*.py /app/mcp/
USER app

CMD ["python", "mcp/remote_server.py"]
