# Battlemap Explorer - Usage Guide

## Quick Start

### Option A: Start Everything at Once (Recommended)

Database and Prefect environment
```bash
docker compose up -d
```

Frontend
```bash
cd frontend
npm run dev
```

Backend
```bash
uv run backend.app.main:app
```

This will automatically start:
- Qdrant (via Docker)
- Backend API at http://localhost:8000
- Frontend at http://localhost:5173

Press Ctrl+C to stop all services.

### Option B: Manual Setup

1. **Reset Database** (Optional):
   ```bash
   python reset_database.py
   ```

2. **Run Image Ingestion**:
   ```bash
   python run_ingestion.py
   ```

3. **Start Services Manually**:

   **Qdrant** (in terminal 1):
   ```bash
   docker-compose up
   ```

   **Backend API** (in terminal 2):
   ```bash
   uv run uvicorn backend.app.main:app --reload
   ```

   **Frontend** (in terminal 3):
   ```bash
   cd frontend
   npm run dev
   ```

### Run Ingestion with UI Monitoring
With the Prefect server running, run the ingestion:
```bash
python run_ingestion.py
```

You'll be able to see:
- Flow execution in real-time
- Task progress and logs
- Success/failure status for each image
- Overall flow statistics

## Daily Workflow

1. **Adding new images**: Just drop them in `data/images/` and run `python run_ingestion.py`
2. **Clearing everything**: Run `python reset_database.py` then re-ingest
3. **Browsing images**: Visit http://localhost:5173
4. **Searching**: Use the search bar or visit the Semantic Search page

## Features

### Gallery View
- Virtual scrolling for performance with large collections
- Quick text search (name, author, tags)
- Click any image to view full details
- Keyboard navigation (arrows) in viewer

### Semantic Search
- Natural language queries: "abandoned mine with crystals"
- Powered by CLIP embeddings
- Results ranked by similarity

### Image Details
- View all metadata and tags
- See dominant colors
- Browse image variants
- Navigate between images

## API Endpoints

- `GET /api/v1/images/` - List all images
- `GET /api/v1/images/{id}` - Get image details
- `GET /api/v1/images/{id}/file` - Download full image
- `GET /api/v1/images/{id}/thumbnail` - Get thumbnail
- `GET /api/v1/search/` - Text/tag search
- `GET /api/v1/search/semantic` - Semantic search
- `GET /api/v1/tags/categories` - List tag categories
- `GET /api/v1/tags/values/{category}` - Get tag values

API docs available at: http://localhost:8000/docs
