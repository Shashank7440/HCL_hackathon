FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# pre-bake the embedding model (venue wifi may be down)
RUN python -c "from sentence_transformers import SentenceTransformer as s; s('sentence-transformers/all-MiniLM-L6-v2')"
COPY . .
ENV DB_PATH=data/app.db CHROMA_PATH=data/chroma
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
