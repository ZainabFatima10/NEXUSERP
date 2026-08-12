from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.forecast  import router as forecast_router
from routes.inventory import router as inventory_router
from routes.predict   import router as predict_router

app = FastAPI(
    title="NEXUS ERP - PowerGrid Optimizer",
    description="AI Forecasting + Inventory Management + VEMA",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(forecast_router, prefix="/api")
app.include_router(inventory_router, prefix="/api")
app.include_router(predict_router,   prefix="/api")

@app.get("/health")
def health():
    return {"status": "running", "version": "2.0.0"}
