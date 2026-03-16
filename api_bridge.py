"""
API الربط مع السيستم الرئيسي — عامر جروب
REST API Bridge — Amer Group
==============================
سيستمك يستدعي هذه الـ Endpoints عند:
  - تسجيل مشترى جديد في أي خط
  - تسجيل دفعة
  - الاستعلام عن رصيد عميل

تشغيل:  uvicorn api_bridge:app --host 0.0.0.0 --port 8000
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, Literal
from database import Database
from datetime import datetime

API_SECRET = os.getenv("API_SECRET", "CHANGE_THIS_SECRET")
BOT_TOKEN  = os.getenv("BOT_TOKEN",  "YOUR_BOT_TOKEN_HERE")

app    = FastAPI(title="Amer Group Bot API", version="2.0", docs_url="/docs")
db     = Database()
_bot   = None   # يُضبط عند تشغيل البوت مع الـ API

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify(key: str = Security(api_key_header)):
    if key != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

# ── النماذج ──────────────────────────────────────────────────────────────────

BusinessType = Literal["grain", "computer", "payments"]

class TransactionIn(BaseModel):
    customer_phone: str
    business:       BusinessType
    amount:         float
    description:    str
    invoice_no:     Optional[str] = None
    notify:         bool = True              # أرسل إشعار تليجرام؟

class PaymentIn(BaseModel):
    customer_phone: str
    business:       BusinessType
    amount:         float
    description:    str = "دفعة"
    notify:         bool = True

class BroadcastIn(BaseModel):
    message: str
    business: Optional[BusinessType] = None  # None = للكل

# ── الـ Endpoints ────────────────────────────────────────────────────────────

@app.post("/purchase", dependencies=[Depends(verify)])
async def register_purchase(data: TransactionIn):
    """
    تسجيل مشترى جديد وإرسال إشعار للعميل.

    مثال من PHP:
    $response = Http::withHeaders(['X-API-Key' => 'سرك'])
        ->post('http://localhost:8000/purchase', [
            'customer_phone' => '01012345678',
            'business'       => 'grain',
            'amount'         => 9000,
            'description'    => 'قمح - 2 طن',
            'invoice_no'     => 'INV-001',
        ]);
    """
    customer = db.get_customer_by_phone(data.customer_phone)
    if not customer:
        raise HTTPException(404, "العميل غير موجود")

    db.add_transaction(customer['id'], data.business, 'purchase',
                       data.amount, data.description, data.invoice_no)
    balance = db.get_balance(customer['id'], data.business)

    if data.notify and customer.get('telegram_id') and _bot:
        ICONS = {"grain": "🌾", "computer": "💻", "payments": "💳"}
        NAMES = {"grain": "الحبوب والأعلاف", "computer": "الكمبيوتر", "payments": "المدفوعات"}
        try:
            await _bot.send_message(
                chat_id=customer['telegram_id'],
                parse_mode="Markdown",
                text=(
                    f"🔔 *فاتورة جديدة — {NAMES[data.business]}*\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"{ICONS[data.business]} *{data.description}*\n"
                    f"💰 القيمة:      *{data.amount:,.2f} ج.م*\n"
                    f"🧾 رقم الفاتورة: `{data.invoice_no or '—'}`\n"
                    f"📅 {datetime.now().strftime('%Y/%m/%d')}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"💼 مديونيتك الحالية: *{balance['net_debt']:,.2f} ج.م*"
                )
            )
        except Exception as e:
            pass  # لو العميل حجب البوت

    return {"ok": True, "new_balance": balance['net_debt']}


@app.post("/payment", dependencies=[Depends(verify)])
async def register_payment(data: PaymentIn):
    """تسجيل دفعة وإرسال إشعار."""
    customer = db.get_customer_by_phone(data.customer_phone)
    if not customer:
        raise HTTPException(404, "العميل غير موجود")

    db.add_transaction(customer['id'], data.business, 'payment',
                       data.amount, data.description)
    balance = db.get_balance(customer['id'], data.business)

    if data.notify and customer.get('telegram_id') and _bot:
        debt_txt = "✅ تم سداد الحساب بالكامل!" if balance['net_debt'] == 0 \
                   else f"💼 المتبقي: *{balance['net_debt']:,.2f} ج.م*"
        try:
            await _bot.send_message(
                chat_id=customer['telegram_id'],
                parse_mode="Markdown",
                text=(
                    f"✅ *تم تسجيل دفعتك*\n"
                    f"💳 المبلغ: *{data.amount:,.2f} ج.م*\n"
                    f"📝 {data.description}\n"
                    f"━━━━━━━━━━━━━━━━━━━\n{debt_txt}"
                )
            )
        except Exception:
            pass

    return {"ok": True, "new_balance": balance['net_debt']}


@app.get("/balance/{phone}", dependencies=[Depends(verify)])
async def get_balance(phone: str):
    """الاستعلام عن رصيد عميل في الثلاث خطوط."""
    customer = db.get_customer_by_phone(phone)
    if not customer:
        raise HTTPException(404, "العميل غير موجود")
    balances = db.get_all_balances(customer['id'])
    total = sum(b['net_debt'] for b in balances.values())
    return {
        "customer": customer['name'],
        "balances": balances,
        "total_debt": total,
        "has_telegram": customer.get('telegram_id') is not None
    }


@app.post("/broadcast", dependencies=[Depends(verify)])
async def broadcast(data: BroadcastIn):
    """إرسال إشعار جماعي لكل العملاء المربوطين."""
    import sqlite3
    conn = sqlite3.connect("amer_group.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT telegram_id FROM customers WHERE telegram_id IS NOT NULL AND is_active=1"
    ).fetchall()
    conn.close()

    sent = 0
    if _bot:
        for row in rows:
            try:
                await _bot.send_message(
                    chat_id=row['telegram_id'],
                    text=data.message,
                    parse_mode="Markdown"
                )
                sent += 1
            except Exception:
                pass
    return {"sent": sent, "total": len(rows)}


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
