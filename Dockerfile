FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads

ENV HOST=0.0.0.0
ENV PORT=5001
ENV SECRET_KEY=""
ENV DEEPSEEK_API_KEY=""
ENV ALIPAY_SANDBOX=true

EXPOSE 5001

CMD ["python", "app.py"]
