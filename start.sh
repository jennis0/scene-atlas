!#/bin/bash

docker compose up -d
uv run uvicorn backend.app.main:app --reload --host &
cd frontend
npm run dev &