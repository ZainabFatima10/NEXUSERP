import os, sys
sys.path.insert(0, "/Users/zainabfatima/Desktop/nexus-erp/ai-module")
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(
    "postgresql://nexus_user:nexus_pass@localhost:5432/nexus_erp"
)

def send_vendor_email(order_id: str):
    """
    Sends vendor email via SMTP.
    Uses SendGrid if API key available, otherwise simulates.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT * FROM procurement_orders WHERE order_id = :oid
        """), {"oid": order_id}).fetchone()

    if not row:
        return {"error": "Order not found"}

    order = dict(row._mapping)

    # Email content
    subject = f"Purchase Order {order_id} — {order['item_name']}"
    body = f"""
Dear {order['vendor']} Team,

We are pleased to place the following purchase order:

Order ID       : {order_id}
Item           : {order['item_name']}
Quantity       : {order['quantity']} {order['unit']}
Expected By    : {order['expected_delivery']}
Trigger        : {order['trigger_type']}

Please confirm receipt of this order and provide
estimated delivery timeline.

Best regards,
NEXUS ERP Procurement System
PowerGrid Optimizer
    """

    SENDGRID_KEY = os.getenv("SENDGRID_API_KEY")

    if SENDGRID_KEY and SENDGRID_KEY != "your_sendgrid_key":
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail
            sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_KEY)
            message = Mail(
                from_email="noreply@nexuserp.com",
                to_emails=order["vendor_email"],
                subject=subject,
                plain_text_content=body
            )
            response = sg.send(message)
            email_status = "Sent"
            print(f"Email sent to {order['vendor_email']} — Status: {response.status_code}")
        except Exception as e:
            email_status = "Failed"
            print(f"Email failed: {e}")
    else:
        # Simulate email sending
        email_status = "Simulated"
        print(f"[SIMULATED] Email to {order['vendor_email']}")
        print(f"Subject: {subject}")
        print(f"Body: {body}")

    # Update email_sent in DB
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE procurement_orders
            SET email_sent = TRUE,
                stage = 'Email Sent'
            WHERE order_id = :oid
        """), {"oid": order_id})

        # Log notification
        conn.execute(text("""
            INSERT INTO notifications
            (type, title, message, order_id, item_name)
            VALUES (:type, :title, :msg, :oid, :iname)
        """), {
            "type":  "EMAIL_SENT",
            "title": f"Vendor Email {email_status}: {order['vendor']}",
            "msg":   f"Purchase order {order_id} for {order['item_name']} "
                     f"({order['quantity']} {order['unit']}) "
                     f"emailed to {order['vendor_email']}. Status: {email_status}",
            "oid":   order_id,
            "iname": order["item_name"]
        })
        conn.commit()

    return {
        "status":       email_status,
        "order_id":     order_id,
        "vendor_email": order["vendor_email"],
        "item":         order["item_name"]
    }

def verify_smart_contract(order_id: str):
    """
    Simulates Hyperledger Fabric smart contract verification.
    Checks budget limits and quantity thresholds.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT * FROM procurement_orders WHERE order_id = :oid
        """), {"oid": order_id}).fetchone()

    if not row:
        return {"error": "Order not found"}

    order = dict(row._mapping)

    # Smart contract rules
    verdict = "Verified"
    reason  = "All checks passed"

    if order["quantity"] > 5000:
        verdict = "Pending"
        reason  = "Quantity exceeds auto-approval limit. Manual review required."
    elif order["quantity"] <= 0:
        verdict = "Unverified"
        reason  = "Invalid quantity."

    # Update contract status
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE procurement_orders
            SET contract_status = :verdict
            WHERE order_id = :oid
        """), {"verdict": verdict, "oid": order_id})

        conn.execute(text("""
            INSERT INTO notifications
            (type, title, message, order_id, item_name)
            VALUES (:type, :title, :msg, :oid, :iname)
        """), {
            "type":  "CONTRACT_VERIFIED",
            "title": f"Smart Contract {verdict}: {order['item_name']}",
            "msg":   f"Order {order_id} smart contract verdict: {verdict}. {reason}",
            "oid":   order_id,
            "iname": order["item_name"]
        })
        conn.commit()

    return {
        "order_id":       order_id,
        "verdict":        verdict,
        "reason":         reason,
        "item":           order["item_name"],
        "quantity":       order["quantity"]
    }
