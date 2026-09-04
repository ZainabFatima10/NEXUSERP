# RBAC Wiring — NEXUS ERP

How role-based access control is layered on top of the existing bcrypt/users-table
auth system (`ai-module/auth.py`, `ai-module/database.py`). Nothing about the
password flow or the `users` table's identity changed — only how the caller's
role is carried on the request and enforced per endpoint.

## Roles

| Role | Value stored in `users.role` | Scope |
|---|---|---|
| Admin | `admin` | Full access to every module, dashboard, endpoint (implicit — every `require_role(...)` check allows `admin` automatically, see below) |
| Customer Representative | `customer_rep` | Complaints/tickets (VEMA + manual), full conversation history, resolve, escalate to Admin |
| Procurement Manager | `procurement_manager` | Inventory visibility, reorder approval/rejection, placing orders, vendor communication dashboard |
| Customer | `customer` | External Customer Portal only — voice/chat complaint intake, own ticket history |

Legacy free-text values from `001_schema.sql` (`Manager`, `Operator`, `Vendor`)
are kept in the `users_role_check` constraint for backward compatibility but
are not used by any route in this codebase.

## Migration — `ai-module/002_add_roles_and_pricing.sql`

Idempotent (safe to re-run every startup — `database.py`'s `run_schema()` now
applies every `NNN_*.sql` file in the directory in order, not just
`001_schema.sql`). It:

1. Adds `inventory_items.unit_price` — referenced throughout `procurement.py` /
   `invoice_service.py` / the frontend types, but missing from the committed
   `001_schema.sql` (docs referenced a `002_add_unit_price.sql` that was never
   actually committed — this migration folds that fix in).
2. Normalizes the seeded `'Admin'` role value to lowercase `'admin'`.
3. Widens the `role` check constraint to the four roles above (+ legacy values).
4. Seeds one Customer Representative and one Procurement Manager test account.

### Seeded test accounts (dev/local only — rotate before any real deployment)

| Role | Email | Password |
|---|---|---|
| Admin | `admin@nexus.pk` | `nexus2026` (from `001_schema.sql`, unchanged) |
| Customer Representative | `cr@nexus.pk` | `nexus2026` |
| Procurement Manager | `procurement@nexus.pk` | `nexus2026` |

All three share the same bcrypt hash as the original seeded Admin purely for
local dev convenience — obviously don't do this outside a dev DB.

## Backend enforcement — `ai-module/rbac.py`

- **Auth changed from opaque token → JWT.** `auth.py`'s `/login` previously
  returned `secrets.token_urlsafe(32)` — a random string with no expiry and no
  way to recover the caller's identity server-side without hitting the DB with
  a client-supplied `user_id` (the old `/api/auth/me?user_id=` had zero
  verification — anyone could read anyone's profile by guessing/enumerating a
  UUID). `python-jose` was already in `requirements.txt` but unused; it's now
  what signs/verifies the token. Response shape (`{user, token}`) is unchanged
  so the frontend's `AuthContext`/`api.ts` didn't need to change how it stores
  or sends the token — only what's inside it changed.
- `get_current_user(request)` — FastAPI dependency, decodes the `Authorization:
  Bearer <jwt>` header, returns `{id, email, name, role}`.
- `require_role(*roles)` — dependency factory. `admin` is **always** implicitly
  included in the allowed set (Admin has full access everywhere), so
  `require_role("procurement_manager")` really means "procurement_manager OR
  admin". Use `require_role_strict(*roles)` for the rare case you need to
  exclude admin.
- `require_role()` with no args = admin-only.
- Set `JWT_SECRET_KEY` in `.env` — falls back to an insecure dev default with a
  printed warning if unset (matches the existing pattern of graceful dev
  fallbacks elsewhere in this codebase, e.g. `email_service.py`'s SMTP dev mode).

### Endpoints gated in this pass

| Router | Endpoints | Required role |
|---|---|---|
| `inventory_v2.py` | `GET /overview`, `GET /item/{id}`, `POST /check`, `POST /predict-inventory`, `GET /demand-forecast` | `procurement_manager` (+ admin) |
| `inventory_v2.py` | `PUT /item/{id}/stock` | admin only |
| `procurement.py` | `POST/GET /orders`, `GET /orders/{id}`, `POST /sign/{id}`, `POST /checkin/{id}`, `GET /checkins/{id}`, `POST /manual-reorder`, `GET .../invoice`, `GET .../invoice/pdf` | `procurement_manager` (+ admin) |
| `procurement.py` | `POST /confirm/{token}` | **unauthenticated by design** — vendor clicks a signed one-time link from their inbox, not a logged-in session |
| `notifications.py` | all | `customer_rep` or `procurement_manager` (+ admin) — everyone with a login sees their own feed |
| `api/routes/forecast.py`, `api/routes/predict.py`, `sales.py` | all | admin only (Outage Prediction / Demand Prediction / Sales analytics are Admin-dashboard-only per `FRONTEND.md`'s nav) |

The public-facing routes intentionally left open: `/health`, `/api/auth/login`,
`/api/auth/signup`, and the vendor-facing `confirm/{token}` link + landing page.
Section 3's vendor accept/reject webhook (added in the next phase) follows the
same pattern — a signed per-order token, not a login.

### `POST /api/auth/signup` no longer accepts a client-supplied role

The original `SignupRequest` had `role: str = "Operator"` and the frontend
`Signup.tsx` even offered an `"Admin"` option in a dropdown — meaning anyone
could self-register as Admin. Public signup now **always** creates a
`customer` account (Customer Portal, Section 5). Admin/CR/Procurement Manager
accounts are provisioned by an existing Admin via the new:

```
POST /api/auth/admin-create-user   (require_role("admin"))
{ "name": ..., "email": ..., "password": ..., "role": "customer_rep" | "procurement_manager" | "admin" }
```

## Frontend — route guards, not just hidden nav

`ProtectedRoute` (`src/components/ProtectedRoute.tsx`) now takes an optional
`allow?: string[]`. No match → `<Navigate>` to that role's own home
(`ROLE_HOME` map: admin→`/admin`, procurement_manager→`/procurement`,
customer_rep→`/cr`, customer→`/portal`), not just a hidden sidebar link.
`App.tsx`'s route tree:

```
/admin/*        allow=["admin"]
/procurement/*  allow=["procurement_manager", "admin"]
/cr/*           allow=["customer_rep", "admin"]
/portal         allow=["customer"]
```

Post-login redirect (`Login.tsx`) now goes to `ROLE_HOME[user.role]` instead
of hardcoding `/admin`.

`Sidebar.tsx` was made reusable (`navItems`/`brandSubtitle` props, default =
the existing admin nav — zero behavior change for Admin) so the new
`ProcurementLayout` and `CRLayout` can share the same sidebar/topbar shell and
visual language instead of duplicating it.

`ProcurementDashboard`, `CRDashboard`, and `CustomerPortal` are placeholder
shells in this pass — they exist so the auth/routing boundary is fully
testable now; Sections 3, 4, and 5 replace them with the real screens.

## What's NOT done in this pass (by design, sequenced into later phases)

- Automated reorder trigger + vendor accept/reject webhook + PM dashboard content → Section 3 (`N8N_AUTOMATION_WIRING.md`)
- VEMA backend (STT/TTS/LLM/complaints) → Section 4 (`VEMA_BACKEND_WIRING.md`)
- Customer Portal voice/chat intake → Section 5 (`CUSTOMER_PORTAL_WIRING.md`)
- CR ticket log / conversation history → Section 6
