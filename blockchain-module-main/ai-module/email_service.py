"""
NEXUS ERP — Email Service
Handles vendor order emails and confirmation token flow.
Uses smtplib with Gmail/SMTP. Configure via .env.
"""
import os
import smtplib
import secrets
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")           # your Gmail
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")       # App password
FROM_NAME     = os.getenv("FROM_NAME", "NEXUS ERP — PowerGrid Optimizer")
BASE_URL      = os.getenv("BASE_URL", "http://localhost:8000")


def generate_confirm_token() -> str:
    """Generate a cryptographically secure confirmation token."""
    return secrets.token_urlsafe(32)


def _send(to_email: str, subject: str, html_body: str) -> bool:
    """Send an HTML email. Returns True on success."""
    if not SMTP_USER or not SMTP_PASSWORD:
        # Dev mode: just print
        print(f"\n📧 [DEV EMAIL] To: {to_email} | Subject: {subject}\n")
        return True
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{FROM_NAME} <{SMTP_USER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"❌ Email send failed: {e}")
        return False


def send_vendor_order_email(
    vendor_email: str,
    vendor_name: str,
    order_code: str,
    item_name: str,
    quantity: float,
    unit: str,
    expected_delivery: str,
    confirm_token: str,
    total_price: float = None,
) -> bool:
    """Send order notification + confirmation link to vendor."""
    confirm_url = f"{BASE_URL}/api/procurement/confirm/{confirm_token}"
    price_row = f"<tr><td><b>Total Price</b></td><td>USD {total_price:,.2f}</td></tr>" if total_price else ""

    html = f"""
    <!DOCTYPE html><html><body style="font-family:DM Sans,Arial,sans-serif;background:#f4f7fb;padding:32px;">
    <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);">
      <div style="background:#001F54;padding:24px 32px;">
        <h2 style="color:#fff;margin:0;font-size:20px;">NEXUS ERP — Purchase Order</h2>
        <p style="color:#a8c4e8;margin:4px 0 0;font-size:13px;">PowerGrid Optimizer · IESCO/LESCO Division</p>
      </div>
      <div style="padding:32px;">
        <p style="color:#333;">Dear <b>{vendor_name}</b>,</p>
        <p style="color:#555;line-height:1.6;">
          NEXUS ERP has generated a purchase order for your organisation. Please review the
          details below and confirm your acceptance by clicking the button.
        </p>
        <table style="width:100%;border-collapse:collapse;margin:20px 0;font-size:14px;">
          <tr style="background:#f0f4fb;">
            <td style="padding:10px 14px;font-weight:600;color:#001F54;">Order ID</td>
            <td style="padding:10px 14px;">{order_code}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;font-weight:600;color:#001F54;">Item</td>
            <td style="padding:10px 14px;">{item_name}</td>
          </tr>
          <tr style="background:#f0f4fb;">
            <td style="padding:10px 14px;font-weight:600;color:#001F54;">Quantity</td>
            <td style="padding:10px 14px;">{quantity:,.0f} {unit}</td>
          </tr>
          {price_row}
          <tr>
            <td style="padding:10px 14px;font-weight:600;color:#001F54;">Expected Delivery</td>
            <td style="padding:10px 14px;">{expected_delivery}</td>
          </tr>
          <tr style="background:#f0f4fb;">
            <td style="padding:10px 14px;font-weight:600;color:#001F54;">Order Date</td>
            <td style="padding:10px 14px;">{datetime.now().strftime('%Y-%m-%d %H:%M')} PKT</td>
          </tr>
        </table>
        <div style="text-align:center;margin:28px 0;">
          <a href="{confirm_url}"
             style="background:#2e7d5e;color:#fff;padding:14px 36px;border-radius:24px;
                    text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">
            ✅ Confirm & Accept Order
          </a>
        </div>
        <p style="color:#888;font-size:12px;line-height:1.6;">
          Upon confirmation, a smart contract will be generated and sent for signing.
          This link expires in 72 hours. If you did not expect this order, please contact
          <a href="mailto:procurement@nexus.pk">procurement@nexus.pk</a>.
        </p>
      </div>
      <div style="background:#f0f4fb;padding:16px 32px;text-align:center;">
        <p style="color:#aaa;font-size:11px;margin:0;">
          NEXUS ERP · FAST-NUCES Islamabad · FYP S26-043
        </p>
      </div>
    </div>
    </body></html>
    """
    return _send(
        vendor_email,
        f"Purchase Order {order_code} — Action Required",
        html,
    )


def send_contract_ready_email(
    vendor_email: str,
    vendor_name: str,
    order_code: str,
    contract_hash: str,
) -> bool:
    """Notify vendor that smart contract is ready."""
    html = f"""
    <!DOCTYPE html><html><body style="font-family:DM Sans,Arial,sans-serif;background:#f4f7fb;padding:32px;">
    <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);">
      <div style="background:#001F54;padding:24px 32px;">
        <h2 style="color:#fff;margin:0;font-size:20px;">Smart Contract Ready</h2>
        <p style="color:#a8c4e8;margin:4px 0 0;font-size:13px;">NEXUS ERP · Blockchain Procurement</p>
      </div>
      <div style="padding:32px;">
        <p>Dear <b>{vendor_name}</b>,</p>
        <p style="color:#555;line-height:1.6;">
          Your order <b>{order_code}</b> has been confirmed and a smart contract has been created
          on the Hyperledger Fabric ledger. The contract will be auto-executed upon verified delivery.
        </p>
        <div style="background:#f0f4fb;border-radius:8px;padding:16px;margin:20px 0;font-family:monospace;font-size:12px;word-break:break-all;">
          <b>Contract Hash:</b><br/>{contract_hash}
        </div>
        <p style="color:#888;font-size:12px;">
          Please retain this hash for your records. The contract will execute automatically
          once delivery is checked in and verified by our warehouse team.
        </p>
      </div>
    </div></body></html>
    """
    return _send(
        vendor_email,
        f"Smart Contract Created — Order {order_code}",
        html,
    )


def send_delivery_notification_email(
    vendor_email: str,
    vendor_name: str,
    order_code: str,
    condition: str,
    quantity_received: float,
    unit: str,
) -> bool:
    """Notify vendor that delivery was checked in."""
    color = "#2e7d5e" if condition == "Good" else "#e65100" if condition == "Damaged" else "#f59e0b"
    html = f"""
    <!DOCTYPE html><html><body style="font-family:DM Sans,Arial,sans-serif;background:#f4f7fb;padding:32px;">
    <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);">
      <div style="background:{color};padding:24px 32px;">
        <h2 style="color:#fff;margin:0;">Delivery Check-In Complete</h2>
        <p style="color:rgba(255,255,255,0.8);margin:4px 0 0;font-size:13px;">Order {order_code}</p>
      </div>
      <div style="padding:32px;">
        <p>Dear <b>{vendor_name}</b>,</p>
        <p>Your delivery for order <b>{order_code}</b> has been received and checked in.</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;">
          <tr style="background:#f0f4fb;">
            <td style="padding:10px 14px;font-weight:600;">Quantity Received</td>
            <td style="padding:10px 14px;">{quantity_received:,.0f} {unit}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;font-weight:600;">Condition</td>
            <td style="padding:10px 14px;color:{color};font-weight:600;">{condition}</td>
          </tr>
          <tr style="background:#f0f4fb;">
            <td style="padding:10px 14px;font-weight:600;">Check-In Date</td>
            <td style="padding:10px 14px;">{datetime.now().strftime('%Y-%m-%d %H:%M')} PKT</td>
          </tr>
        </table>
        {"<p style='color:#2e7d5e;font-weight:600;'>✅ Smart contract has been executed. Payment will be processed per agreed terms.</p>" if condition == "Good" else "<p style='color:#e65100;'>⚠️ Our team will be in contact regarding the delivery condition.</p>"}
      </div>
    </div></body></html>
    """
    return _send(
        vendor_email,
        f"Delivery Received — Order {order_code}",
        html,
    )


def send_internal_notification_email(
    to_email: str,
    subject: str,
    body_html: str,
) -> bool:
    """Generic internal notification (to admin/manager)."""
    html = f"""
    <!DOCTYPE html><html><body style="font-family:DM Sans,Arial,sans-serif;background:#f4f7fb;padding:32px;">
    <div style="max-width:560px;margin:auto;background:#fff;border-radius:12px;overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);">
      <div style="background:#001F54;padding:20px 32px;">
        <h2 style="color:#fff;margin:0;font-size:18px;">NEXUS ERP Notification</h2>
      </div>
      <div style="padding:32px;">
        {body_html}
      </div>
      <div style="background:#f0f4fb;padding:12px 32px;text-align:center;">
        <p style="color:#aaa;font-size:11px;margin:0;">NEXUS ERP · Auto-generated · Do not reply</p>
      </div>
    </div></body></html>
    """
    return _send(to_email, subject, html)
