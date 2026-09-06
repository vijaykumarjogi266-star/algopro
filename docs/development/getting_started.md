# Algo Lab — Developer Setup & Quickstart

## Prerequisites
- Linux or macOS
- Python 3.12+
- Node.js 20+ and npm
- Docker & Docker Compose

---

## 1. Local Environment Setup

### Clone Repository & Enter Directory
```bash
cd algo-lab
```

### Python Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### Node.js Frontend Dependencies
```bash
cd apps/web
npm install
cd ../..
```

---

## 2. Running Services with Docker Compose

To start PostgreSQL and local database infrastructure:
```bash
docker compose up -d postgres
```

To run the entire suite (PostgreSQL + API):
```bash
docker compose up -d
```

---

## 3. Running Services Locally

### FastAPI Backend Server
```bash
source .venv/bin/activate
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```
- API Docs: `http://localhost:8000/docs`
- Health Liveness: `http://localhost:8000/health`
- Health Readiness: `http://localhost:8000/health/ready`
- System Info: `http://localhost:8000/api/v1/system/info`
- Principles: `http://localhost:8000/api/v1/system/principles`

### Next.js Frontend Web Shell
```bash
cd apps/web
npm run dev
```
- Web App UI: `http://localhost:3000`

---

## 4. Running the Test Suite

Run all unit tests, contract validations, and code coverage:
```bash
source .venv/bin/activate
pytest tests/ --cov=apps --cov=quant --cov=services --cov=data
```

Run Next.js build verification:
```bash
cd apps/web
npm run build
```
