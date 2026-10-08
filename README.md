# NEXUS ERP — PowerGrid Optimizer
### AI Forecasting & Inventory Management Module

**FAST-NUCES Islamabad | FYP S26-043 | Session 2022–2026**

> An intelligent single-portal ERP system for Pakistan's electricity sector, featuring AI-driven outage prediction, automated inventory management, and VEMA voice automation.

---

## Team

| Name | Roll No |
|---|---|
| Zainab Fatima | 22I-1064 |
| Ayesha Tahir | 22i-0480 |
| Ayesha Imran | 22i-1942 |

**Supervisors:** Mr. Ahmed Raza, Dr. Noshina Tariq

---

## Model Performance

| Module | Model | Accuracy |
|---|---|---|
| Outage Prediction | XGBoost Classifier | **89.8%** |
| Inventory Demand Forecasting | XGBoost Regressor | **94.9%** (R²) |
| Outage Model ROC-AUC | — | **0.8865** |
| Demand Model MAE | — | **15 KWh** |

> FYP target accuracy: 85% — both models exceed this threshold.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React.js + Tailwind CSS (Lovable) |
| Backend | FastAPI + Python 3.11 |
| ML Models | XGBoost, scikit-learn |
| Database | PostgreSQL 14 (Docker) + TimescaleDB |
| Blockchain | Hyperledger Fabric (simulated) |
| Voice Agent (VEMA) | Local Whisper (STT) + Local Kokoro (TTS) + Mistral API (NLU/conversation) |
| Tunneling | Cloudflare Tunnel |

---

## Project Structure

```
nexus-erp/
├── ai-module/
│   ├── api/
│   │   ├── main.py                  # FastAPI app entry point
│   │   ├── database.py              # PostgreSQL connection
│   │   └── routes/
│   │       ├── forecast.py          # Outage prediction endpoints
│   │       ├── inventory.py         # Inventory management endpoints
│   │       └── predict.py           # ML demand prediction endpoint
│   ├── data/
│   │   ├── generate_sample.py       # Outage training data generator
│   │   ├── generate_inventory.py    # Inventory items data generator
│   │   ├── generate_inventory_ml.py # Inventory ML training data
│   │   ├── collect_weather.py       # Open-Meteo API collector (Free)
│   │   ├── raw/                     # Raw CSV files
│   │   ├── processed/               # Cleaned training datasets
│   │   └── inventory/               # Inventory JSON data
│   ├── models/
│   │   ├── train.py                 # Outage + demand model training
│   │   ├── train_inventory.py       # Inventory demand model training
│   │   ├── inventory_engine.py      # Rule-based threshold engine
│   │   ├── validate_inventory.py    # Business rule validation
│   │   └── saved/                   # Trained .pkl model files
│   ├── docker-compose.yml           # PostgreSQL container
│   ├── requirements.txt
│   └── .env                         # Environment variables (not committed)
└── frontend/                        # React frontend (Lovable export)
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | System health check |
| GET | `/api/forecast` | 7-day outage probability forecast |
| GET | `/api/forecast/{date}` | Single day forecast detail |
| GET | `/api/inventory/overview` | All items with OK/Low/Critical status |
| GET | `/api/inventory/orders/current` | Active procurement orders |
| GET | `/api/inventory/orders/history` | Past delivered orders |
| POST | `/api/inventory/check` | Trigger auto order generation |
| POST | `/api/inventory/reorder/{item_id}` | Manual reorder |
| POST | `/api/predict` | ML inventory demand prediction |

Full interactive docs available at: `http://localhost:8000/docs`

---

## Setup & Running

### Prerequisites
- Python 3.11
- Docker Desktop
- Git

### 1. Clone the repo
```bash
git clone https://github.com/ZainabFatima10/NEXUSERP.git
cd NEXUSERP/blockchain-module-main/ai-module
```

### 2. Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # Mac/Linux
pip install -r requirements.txt
```

### 3. Set up environment variables
Create a `.env` file in `ai-module/`:
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=nexus_erp
DB_USER=nexus_user
DB_PASSWORD=nexus_pass
```

### 4. Start the database
```bash
docker-compose up -d
```

### 5. Generate training data & train models
```bash
python data/generate_sample.py
python data/generate_inventory.py
python data/generate_inventory_ml.py
python models/train.py
python models/train_inventory.py
```

### 6. Start the API server
```bash
cd api
uvicorn main:app --reload --port 8000
```

### 7. (Optional) Expose to internet via Cloudflare Tunnel
```bash
cloudflared.exe tunnel --url http://localhost:8000
```

---

## Business Rules — Inventory Thresholds

| Status | Condition | Action |
|---|---|---|
| OK | `stock >= min_threshold` | Routine monitoring |
| Low | `stock < min_threshold` | Auto-Generated order |
| Critical | `stock <= min_threshold × 20%` | VEMA-Triggered order |

---

## Forecast Risk Levels

| Risk Level | Outage Probability | Color |
|---|---|---|
| Low | < 40% | Green |
| Medium | 40% – 70% | Amber |
| High | > 70% | Red |

---

## Modules Status

| Module | Status | Iteration |
|---|---|---|
| AI Outage Forecasting | Complete | 1 |
| Inventory Management | Complete | 1 |
| Blockchain Procurement (simulated Hyperledger Fabric) | Complete | 2 |
| Automated Reordering + Procurement Manager approval + n8n | Complete | 2 |
| Role-Based Access Control (Admin / CR / Procurement Manager / Customer) | Complete | 2 |
| VEMA Voice/Chat Agent (Whisper + Kokoro + Mistral) | Complete | 3 |
| Customer Portal | Complete | 3 |
| Notifications | Complete | 2 |

See `RBAC_WIRING.md`, `N8N_AUTOMATION_WIRING.md`, `VEMA_BACKEND_WIRING.md`,
and `CUSTOMER_PORTAL_WIRING.md` for how each of these is actually wired, and
`CLAUDE.md` for a full map of the codebase.

---

## License
This project is developed for academic purposes as part of the Final Year Project at FAST-NUCES Islamabad.
