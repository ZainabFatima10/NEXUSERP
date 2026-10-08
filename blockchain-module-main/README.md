# NEXUS ERP — PowerGrid Optimizer
### AI Forecasting & Inventory Management Module

**FAST-NUCES Islamabad | FYP S26-043 | Session 2022–2026**

> An intelligent single-portal ERP system for Pakistan's electricity sector, featuring AI-driven outage prediction, automated inventory management, and VEMA voice automation.

---

## Team

| Name | Roll No | Responsibility |
|---|---|---|
| Zainab Fatima | 22I-1064 | Blockchain procurement, smart contracts, vendor email, TimescaleDB |
| Ayesha Tahir | 22i-0480 | AI forecasting, data collection, model training, visualization |
| Ayesha Imran | 22i-1942 | VEMA voice automation, testing, documentation, React frontend |

**Supervisors:** Mr. Ahmed Raza, Dr. Noshina Tariq

---

## Model Performance

| Module | Model | Accuracy |
|---|---|---|
| Outage Prediction | XGBoost Classifier | **89.8%** |
| Inventory Demand Forecasting | XGBoost Regressor | **94.9%** (R²) |
| Outage Model ROC-AUC | — | **0.8865** |
| Demand Model MAE | — | **15 KWh** |

> FYP target accuracy: 85% — both models exceed this threshold ✅

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React.js + Tailwind CSS (Lovable) |
| Backend | FastAPI + Python 3.11 |
| ML Models | XGBoost, scikit-learn |
| Database | PostgreSQL 14 (Docker) + TimescaleDB |
| Blockchain | Hyperledger Fabric (planned Iteration 2) |
| Voice Agent | Whisper + Rasa + Google TTS (planned Iteration 3) |
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
│   │   ├── collect_weather.py       # OpenWeather API collector
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
git clone https://github.com/ayeshat157-rgb/nexus-erp.git
cd nexus-erp/ai-module
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
OPENWEATHER_API_KEY=your_key_here
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
| ✅ OK | `stock >= min_threshold` | Routine monitoring |
| ⚠️ Low | `stock < min_threshold` | Auto-Generated order |
| 🔴 Critical | `stock <= min_threshold × 20%` | VEMA-Triggered order |

---

## Forecast Risk Levels

| Risk Level | Outage Probability | Color |
|---|---|---|
| Low | < 40% | 🟢 Green |
| Medium | 40% – 70% (inclusive) | 🟡 Amber |
| High | > 70% (71% – 100%) | 🔴 Red |

---

## Modules Status

| Module | Status | Iteration |
|---|---|---|
| AI Outage Forecasting | ✅ Complete | 1 |
| Inventory Management | ✅ Complete | 1 |
| Blockchain Procurement | 🔄 Planned | 2 |
| VEMA Voice Agent | 🔄 Planned | 3 |
| Notifications | 🔄 Planned | 2 |

---

## Inventory Items Monitored

| Item | Min Threshold | Unit | Vendor |
|---|---|---|---|
| Distribution Transformers (11kV) | 50 | units | Siemens AG |
| Circuit Breakers (33kV) | 30 | units | ABB Ltd |
| Power Cables (HT) | 5000 | meters | Nexans |
| Smart Meters (AMI) | 200 | units | Siemens AG |
| Surge Arresters | 100 | units | ABB Ltd |
| Insulators (Porcelain) | 500 | units | NGK Insulators |
| Relay Protection Units | 40 | units | Schneider |
| Copper Conductors | 1000 | kg | Prysmian Group |

---

## License
This project is developed for academic purposes as part of the Final Year Project at FAST-NUCES Islamabad.