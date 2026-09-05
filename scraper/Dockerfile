FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium
COPY db ./db
COPY scraper ./scraper
ENV PYTHONPATH=/app
CMD ["python", "-m", "scraper.run"]
