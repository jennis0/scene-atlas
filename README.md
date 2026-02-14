# Battlemap Explorer

A powerful local system for managing, searching, and exploring tens of thousands of RPG battlemap images with advanced features including semantic image search, multi-dimensional tag-based filtering, and color search.

## Features

- **Semantic Image Search**: Search images using natural language queries (e.g., "dark forest cave with water")
- **Multi-dimensional Tag System**: Filter by grid type, season, lighting, state, theme, weather, and more
- **Color Search**: Find maps by dominant colors
- **Variant Management**: Group related map variants together
- **Metadata Extraction**: Automatically infer tags, author, and base name from file paths and names
- **Scalable**: Built to handle tens of thousands of images efficiently
- **100% Local**: No cloud services required, runs entirely on your machine

## Tech Stack

- **Backend**: Python, FastAPI, SQLite, Qdrant
- **ML**: CLIP (OpenAI) for semantic embeddings
- **Orchestration**: Prefect for image processing workflows
- **Frontend**: React + Vite (Phase 2)

## Prerequisites

- Python 3.11+
- Docker (for Qdrant)
- UV package manager
- (Optional) CUDA-capable GPU for faster embedding generation

## Installation

### 1. Install UV

UV is already installed based on your previous message.

### 2. Install Dependencies

```bash
# Install Python dependencies
uv sync
```

### 3. Start Qdrant

```bash
# Start Qdrant vector database
docker-compose up -d
```

### 4. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env if needed (defaults should work for local development)
```

## Usage

### Start the API Server

```bash
# From the project root
cd backend
uv run python -m app.main
```

The API will be available at `http://localhost:8000`

- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### Run Image Ingestion

#### Option 1: Using Python Script

```python
from pathlib import Path
from backend.flows import bulk_image_ingestion

# Ingest images from directories
result = bulk_image_ingestion(
    source_dirs=[
        "/path/to/your/battlemaps",
        "/path/to/more/maps",
    ]
)

print(f"Processed: {result['successful']} successful, {result['failed']} failed")
```

#### Option 2: Using Prefect UI (Recommended)

```bash
# Start Prefect server
uv run prefect server start

# In another terminal, run the flow
uv run python -c "from backend.flows import bulk_image_ingestion; bulk_image_ingestion(['/path/to/maps'])"
```

Visit `http://localhost:4200` to see the Prefect UI with flow runs and logs.

### API Examples

#### Search Images

```bash
# Text search
curl "http://localhost:8000/api/v1/search/?text=forest"

# Semantic search
curl "http://localhost:8000/api/v1/search/?semantic=dark+cave+with+water"

# Filter by tags
curl "http://localhost:8000/api/v1/search/?tags=season:winter&tags=lighting:night"

# Combined search
curl "http://localhost:8000/api/v1/search/?semantic=tavern&tags=grid:gridded&author=DungeonDraft"
```

#### List Tag Categories

```bash
curl "http://localhost:8000/api/v1/tags/categories"
```

#### Get Tag Statistics

```bash
curl "http://localhost:8000/api/v1/tags/stats"
```

## Project Structure

```
battlemap-explorer/
├── backend/
│   ├── app/                    # FastAPI application
│   │   ├── api/               # API endpoints
│   │   ├── models/            # Database models & schemas
│   │   ├── services/          # Business logic (CLIP, Qdrant)
│   │   ├── config.py          # Configuration
│   │   └── main.py            # FastAPI app entry point
│   └── flows/                 # Prefect workflows
│       ├── tasks/             # Individual processing tasks
│       ├── parsers/           # Creator-specific parsers
│       └── ingestion.py       # Main ingestion flow
├── frontend/                  # React frontend (Phase 2)
├── data/
│   ├── images/               # Original images
│   ├── thumbnails/           # Generated thumbnails
│   ├── battlemap.db          # SQLite database
│   └── qdrant_storage/       # Qdrant vector database
├── config/
│   └── parser_rules.yaml     # Custom parsing rules
├── docker-compose.yml        # Qdrant container
├── pyproject.toml           # Python dependencies
└── README.md
```

## Tag System

The tag system supports multidimensional variant categorization:

- **grid**: gridded, no-grid, hex-grid
- **lighting**: day, night, dusk, dawn, twilight
- **season**: spring, summer, fall, winter
- **state**: normal, bloody, ruined, abandoned, overgrown, burned
- **theme**: fey, shadow, fire, ice, underdark, astral, ethereal
- **weather**: clear, rain, snow, fog, storm, mist
- **population**: empty, furnished, populated, battle
- **perspective**: top-down, isometric, side-view
- **quality**: line-art, colored, rendered, sketch

Tags are automatically extracted from filenames and paths using pattern matching.

## Database Schema

### SQLite Tables

- **images**: Main image metadata
- **tags**: Tag assignments (category + value)
- **colors**: Dominant colors per image
- **variant_groups**: Groups related image variants
- **tag_categories**: Tag taxonomy definitions

### Qdrant Collection

- **battlemap_images**: CLIP embeddings (512-dim vectors) with metadata

## Development

### Linting

```bash
# Run Ruff linter
uv run ruff check .

# Auto-fix issues
uv run ruff check . --fix

# Format code
uv run ruff format .
```

### Testing

```bash
# Run tests (when implemented)
uv run pytest
```

## Roadmap

### Phase 1: Core Infrastructure ✅ (Current)
- [x] Backend API with FastAPI
- [x] SQLite database with tag system
- [x] Qdrant vector database
- [x] CLIP embedding generation
- [x] Prefect ingestion pipeline
- [x] Multi-faceted search API

### Phase 2: Frontend (Next)
- [ ] React frontend with Vite
- [ ] Virtual scrolling image grid
- [ ] Search and filter UI
- [ ] Image viewer with variants
- [ ] Manual metadata editor

### Phase 3: Advanced Features
- [ ] Variant detection and auto-grouping
- [ ] Creator-specific parser rules
- [ ] Bulk metadata operations
- [ ] Import/export functionality
- [ ] Performance optimizations

## Configuration

### Custom Parser Rules

Create custom parsing rules for specific creators in `config/parser_rules.yaml`:

```yaml
creators:
  - name: "Dungeon Alchemist"
    path_pattern: "**/DungeonAlchemist/**"
    filename_pattern: "{mapname}_{variant1}_{variant2}_{grid}.png"
    tag_mappings:
      grid:
        - pattern: "Grid"
          value: "gridded"
```

## Troubleshooting

### Qdrant Connection Errors

Make sure Qdrant is running:
```bash
docker-compose ps
docker-compose logs qdrant
```

### CLIP Model Download

On first run, CLIP model will download (~600MB). This may take time.

### Out of Memory

If processing large batches, reduce parallel processing or use smaller thumbnail sizes in `config.py`.

## License

MIT

## Contributing

Contributions welcome! Please open an issue first to discuss changes.
