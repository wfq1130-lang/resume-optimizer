FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpango-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi8 \
    libcairo2 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads /app/data

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=5001
ENV BACKEND_PORT=5002
ENV BACKEND_URL=http://127.0.0.1:5002
ENV DATA_DIR=/app/data
ENV SECRET_KEY=""
ENV JWT_SECRET=""
ENV DEEPSEEK_API_KEY=""
ENV ALIPAY_SANDBOX=true

EXPOSE 5001

CMD ["bash", "start.sh"]
