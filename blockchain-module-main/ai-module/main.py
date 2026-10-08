"""
NEXUS ERP — Main FastAPI Application (Module 2)
Merges Module 1 (outage prediction) with Module 2 (blockchain procurement).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# Module 1 routes (existing)
from api.routes.forecast  import router as forecast_router
from api.routes.predict   import router as predict_router

# Module 2 routes (new)
from inventory_v2  import router as inventory_router
from procurement   import router as procurement_router
from notifications import router as notifications_router
from auth          import router as auth_router
from sales         import router as sales_router
from complaints    import router as complaints_router
from rag_router    import router as rag_router
from vendors       import router as vendors_router
from vendor_orders import router as vendor_orders_router
from payments      import router as payments_router

from database import check_connection, run_schema
from reminder_scheduler import start_scheduler, stop_scheduler

app = FastAPI(
    title="NEXUS ERP — PowerGrid Optimizer",
    description="AI Forecasting + Blockchain Procurement for Pakistan DISCOs",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
app.include_router(forecast_router,      prefix="/api")
app.include_router(predict_router,       prefix="/api")
app.include_router(inventory_router)
app.include_router(procurement_router)
app.include_router(notifications_router)
app.include_router(auth_router)
app.include_router(sales_router)
app.include_router(complaints_router)
app.include_router(rag_router)
app.include_router(vendors_router)
app.include_router(vendor_orders_router)
app.include_router(payments_router)


@app.on_event("startup")
def on_startup():
    """Apply schema migrations on every startup (idempotent)."""
    try:
        run_schema()
        print("[OK] DB schema verified.")
    except Exception as e:
        print(f"[WARN] Schema migration warning: {e}")
    start_scheduler()

    # Re-order every item currently labelled Critical (skips items that
    # already have an open order). Must never stop the server from booting.
    try:
        from inventory_v2 import reorder_critical_items_on_startup
        reorder_critical_items_on_startup()
    except Exception as e:
        print(f"[ERROR] Startup re-order check failed: {e}")


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


@app.get("/health")
def health():
    db_ok = check_connection()
    return {
        "status":       "running",
        "module":       "NEXUS ERP",
        "version":      "2.0.0",
        "db_connected": db_ok,
        "features": [
            "Outage Prediction (XGBoost)",
            "Demand Forecasting (XGBoost)",
            "Inventory Management (PostgreSQL)",
            "Blockchain Procurement (Hyperledger Fabric sim)",
            "Smart Contract Lifecycle",
            "Delivery Check-In & Tracking",
            "Notifications",
        ],
    }


# Vendor confirmation landing page (opens from email link)
@app.get("/api/procurement/confirm/{token}", response_class=HTMLResponse)
async def confirm_landing(token: str):
    """
    GET version of confirm — shows a nice landing page.
    The POST /confirm/{token} does the actual DB work.
    The frontend can also call POST directly.
    """
    return f"""
    <!DOCTYPE html><html>
    <head>
      <title>NEXUS ERP — Confirm Order</title>
      <style>
        body{{font-family:'DM Sans',Arial,sans-serif;background:#f4f7fb;
              display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
        .card{{background:#fff;border-radius:16px;padding:48px;max-width:480px;width:90%;
               box-shadow:0 8px 32px rgba(0,0,0,0.10);text-align:center}}
        h1{{color:#001F54;font-size:24px;margin-bottom:8px}}
        p{{color:#555;line-height:1.6;margin-bottom:24px}}
        button{{background:#001F54;color:#fff;border:none;border-radius:24px;
                padding:14px 40px;font-size:16px;font-weight:700;cursor:pointer;
                transition:background 0.2s}}
        button:hover{{background:#2e7d5e}}
        .success{{display:none;color:#2e7d5e;font-weight:600;margin-top:16px;font-size:18px}}
        .error{{display:none;color:#c62828;font-weight:600;margin-top:16px}}
      </style>
    </head>
    <body>
    <div class="card">
      <h1>NEXUS ERP</h1>
      <p>You have received a purchase order from <strong>PowerGrid Optimizer</strong>.
         Click below to confirm acceptance and initiate the smart contract process.</p>
      <button onclick="confirmOrder()">✅ Confirm Order</button>
      <div class="success" id="ok">✅ Order confirmed! Smart contract has been created.</div>
      <div class="error"   id="err">❌ This link is invalid or has already been used.</div>
    </div>
    <script>
    async function confirmOrder() {{
      try {{
        const res = await fetch('/api/procurement/confirm/{token}', {{method:'POST'}});
        const data = await res.json();
        if (res.ok) {{
          document.getElementById('ok').style.display  = 'block';
          document.querySelector('button').style.display = 'none';
        }} else {{
          document.getElementById('err').textContent = data.detail || 'Error';
          document.getElementById('err').style.display = 'block';
        }}
      }} catch(e) {{
        document.getElementById('err').style.display = 'block';
      }}
    }}
    </script>
    </body></html>
    """


# Vendor accept/reject landing page (opens from the reorder-approval email's
# Accept/Reject buttons). A plain <a href> is a GET request — the actual
# decision endpoint is POST-only (mirrors /confirm/{token} above) — and
# requiring an explicit click before the POST fires also protects against
# email/security scanners that silently pre-fetch links.
@app.get("/api/procurement/vendor-response/{order_id}", response_class=HTMLResponse)
async def vendor_response_landing(order_id: str, decision: str, token: str):
    is_accept = decision == "accept"
    label = "Accept" if is_accept else "Reject"
    color = "#2e7d5e" if is_accept else "#c62828"
    icon = "✅" if is_accept else "❌"
    action_url = f"/api/procurement/vendor-response/{order_id}?decision={decision}&token={token}"
    return f"""
    <!DOCTYPE html><html>
    <head>
      <title>NEXUS ERP — {label} Order</title>
      <style>
        body{{font-family:'DM Sans',Arial,sans-serif;background:#f4f7fb;
              display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
        .card{{background:#fff;border-radius:16px;padding:48px;max-width:480px;width:90%;
               box-shadow:0 8px 32px rgba(0,0,0,0.10);text-align:center}}
        h1{{color:#001F54;font-size:24px;margin-bottom:8px}}
        p{{color:#555;line-height:1.6;margin-bottom:24px}}
        button{{background:{color};color:#fff;border:none;border-radius:24px;
                padding:14px 40px;font-size:16px;font-weight:700;cursor:pointer;
                transition:opacity 0.2s}}
        button:hover{{opacity:0.85}}
        .success{{display:none;color:{color};font-weight:600;margin-top:16px;font-size:18px}}
        .error{{display:none;color:#c62828;font-weight:600;margin-top:16px}}
      </style>
    </head>
    <body>
    <div class="card">
      <h1>NEXUS ERP</h1>
      <p>Confirm your decision on this purchase order.</p>
      <button onclick="sendDecision()">{icon} {label} Order</button>
      <div class="success" id="ok"></div>
      <div class="error"   id="err">This link is invalid or has already been used.</div>
    </div>
    <script>
    async function sendDecision() {{
      try {{
        const res = await fetch('{action_url}', {{method:'POST'}});
        const data = await res.json();
        if (res.ok) {{
          document.getElementById('ok').textContent = data.message || 'Recorded.';
          document.getElementById('ok').style.display = 'block';
          document.querySelector('button').style.display = 'none';
        }} else {{
          document.getElementById('err').textContent = data.detail || 'Error';
          document.getElementById('err').style.display = 'block';
        }}
      }} catch(e) {{
        document.getElementById('err').style.display = 'block';
      }}
    }}
    </script>
    </body></html>
    """
