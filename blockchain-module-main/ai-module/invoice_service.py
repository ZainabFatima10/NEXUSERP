"""
NEXUS ERP - Invoice Service
Generates structured invoice JSON and PDF for procurement orders.
"""
from datetime import datetime
import io


def generate_invoice_data(order: dict) -> dict:
    unit_price = order.get("unit_price")
    quantity = float(order.get("quantity") or 0)
    subtotal = round(float(quantity) * float(unit_price), 2) if unit_price is not None else None

    fee_rate = 0.005
    tax_rate = 0.00

    fee = round(subtotal * fee_rate, 2) if subtotal is not None else None
    tax = round(subtotal * tax_rate, 2) if subtotal is not None else None
    total = round(subtotal + (fee or 0) + (tax or 0), 2) if subtotal is not None else None

    order_code = order.get("order_code", "ORD-000000")
    inv_num = "INV-" + order_code.replace("ORD-", "")

    return {
        "invoice_number": inv_num,
        "order_code": order_code,
        "issued_at": str(order.get("created_at", datetime.utcnow().isoformat())),
        "status": "Generated" if order.get("stage") != "Cancelled" else "Cancelled",
        "company": {
            "name": "NEXUS ERP PowerGrid Optimizer",
            "tagline": "Smart Grid & Automated Procurement Network",
            "address": "Islamabad Electric Supply Company (IESCO) HQ, Islamabad, Pakistan",
            "email": "procurement@nexus.pk"
        },
        "vendor": {
            "name": order.get("vendor_name", "Unknown Vendor"),
            "email": order.get("vendor_email", "vendor@nexus.pk")
        },
        "line_items": [
            {
                "description": order.get("item_name", "Equipment/Spare Part"),
                "item_id": order.get("item_id", "INV-000"),
                "quantity": quantity,
                "unit": order.get("unit", "units"),
                "unit_price": unit_price,
                "line_total": subtotal
            }
        ],
        "subtotal": subtotal,
        "blockchain_fee_rate": fee_rate,
        "blockchain_fee": fee,
        "tax_rate": tax_rate,
        "tax": tax,
        "total": total,
        "currency": "PKR",
        "contract_hash": order.get("contract_hash"),
        "contract_status": order.get("contract_status"),
        "expected_delivery": order.get("expected_delivery"),
        "trigger_type": order.get("trigger_type", "Manual"),
        "pricing_pending": subtotal is None
    }


def generate_invoice_pdf(invoice: dict) -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = []

        title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=22, leading=26, textColor=colors.HexColor("#0F172A"))
        sub_style = ParagraphStyle("SubStyle", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#64748B"))
        bold_style = ParagraphStyle("BoldStyle", parent=styles["Normal"], fontSize=10, leading=14, textColor=colors.HexColor("#0F172A"), fontName="Helvetica-Bold")

        header_data = [[
            Paragraph("<b>NEXUS ERP</b><br/><font size=8 color='#64748B'>PowerGrid Optimizer</font>", title_style),
            Paragraph(f"<b>INVOICE</b><br/><font size=9 color='#64748B'>#{invoice['invoice_number']}<br/>Order: {invoice['order_code']}</font>", ParagraphStyle("R", parent=sub_style, alignment=2))
        ]]
        t_header = Table(header_data, colWidths=[270, 270])
        t_header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t_header)
        story.append(Spacer(1, 15))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#E2E8F0"), spaceAfter=15))

        party_data = [[
            Paragraph(f"<b>Billed To:</b><br/>{invoice['company']['name']}<br/>{invoice['company']['address']}<br/>{invoice['company']['email']}", sub_style),
            Paragraph(f"<b>Vendor:</b><br/>{invoice['vendor']['name']}<br/>{invoice['vendor']['email']}<br/><b>Delivery By:</b> {invoice.get('expected_delivery') or 'TBD'}", sub_style)
        ]]
        t_party = Table(party_data, colWidths=[270, 270])
        t_party.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t_party)
        story.append(Spacer(1, 20))

        cur = invoice.get("currency") or "PKR"
        items_data = [[Paragraph("<b>Item Description</b>", bold_style), Paragraph("<b>Qty</b>", bold_style), Paragraph("<b>Unit Price</b>", bold_style), Paragraph("<b>Total</b>", bold_style)]]
        for item in invoice["line_items"]:
            price_str = f"{cur} {item['unit_price']:,.2f}" if item["unit_price"] is not None else "Pending"
            tot_str = f"{cur} {item['line_total']:,.2f}" if item["line_total"] is not None else "Pending"
            items_data.append([
                Paragraph(f"{item['description']}<br/><font size=8 color='#64748B'>SKU: {item['item_id']}</font>", sub_style),
                Paragraph(f"{item['quantity']} {item['unit']}", sub_style),
                Paragraph(price_str, sub_style),
                Paragraph(tot_str, bold_style)
            ])

        t_items = Table(items_data, colWidths=[240, 90, 100, 110])
        t_items.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ]))
        story.append(t_items)
        story.append(Spacer(1, 15))

        sub_val = f"{cur} {invoice['subtotal']:,.2f}" if invoice["subtotal"] is not None else "Pending"
        fee_val = f"{cur} {invoice['blockchain_fee']:,.2f}" if invoice["blockchain_fee"] is not None else "Pending"
        tot_val = f"{cur} {invoice['total']:,.2f}" if invoice["total"] is not None else "Pending"

        summary_data = [
            ["Subtotal:", sub_val],
            [f"Blockchain Verification Fee ({invoice.get('blockchain_fee_rate', 0.005) * 100:g}%):", fee_val],
            ["Total Payable:", tot_val],
        ]
        t_sum = Table(summary_data, colWidths=[380, 160])
        t_sum.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
            ("FONTSIZE", (0, 2), (-1, 2), 11),
            ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#0F172A")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t_sum)
        story.append(Spacer(1, 25))

        tx_hash = invoice.get("contract_hash") or "Pending smart contract execution"
        bc_note = f"<b>Blockchain Audit Record:</b><br/>Tx Hash: <font face='Courier'>{tx_hash}</font><br/>Contract Status: {invoice.get('contract_status') or 'Pending'}"
        story.append(Paragraph(bc_note, sub_style))

        doc.build(story)
        buffer.seek(0)
        return buffer.read()
    except Exception:
        txt = f"NEXUS ERP Invoice {invoice.get('invoice_number')} - Total: {invoice.get('total')}"
        return txt.encode("utf-8")