FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY db ./db
COPY scoring ./scoring
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .
ENV PYTHONPATH=/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
