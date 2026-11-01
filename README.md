# IRCTC Universal Pathfinder Backend

A high-performance FastAPI backend engine for Indian Railways train availability, booking optimization, split-station route discovery, and real-time waitlist ranking.

## Features

- **FastAPI Core**: Async REST and SSE streaming endpoints for train searches.
- **Smart Scoring & Ranking**:
  - Tier 0: Confirmed seats first
  - Tier 1: RAC (guaranteed boarding)
  - Tier 2: Waitlist sorted from lowest to highest waiting list numbers
  - Tier 3: Regret
- **Station Break & Corridor Engine**: Dynamic geographic detour ratio calculation across national rail corridor hubs (Bareilly, Moradabad, Kanpur, Banaras, Prayagraj, etc.) to discover confirmed connecting routes on demand.
- **IRCTC Lifehacks**: Same-train split tickets and point-beyond quota hacking.

## Setup & Running

### 1. Requirements
- Python 3.10+
- Pip

### 2. Installation
```bash
pip install -r requirements.txt
```

### 3. Run the Server
```bash
python run.py
```
Or with Uvicorn:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

- `GET /api/health` - Service health status
- `GET /api/stations/search?q={query}` - 8,500+ Indian railway stations autocomplete
- `GET /api/search?from={SRC}&to={DST}&date={DD-MM-YYYY}&quota=GN&split_stations=false` - Train search with smart ranking and optional split-station discovery
- `GET /api/trains/{train_no}/schedule` - Live train schedule and platform halts

