"""
╔══════════════════════════════════════════════════════════╗
║          بوت تليجرام - عامر جروب                        ║
║          Telegram Bot - Amer Group                       ║
║  ✦ محل الحبوب والأعلاف  ✦ محل الكمبيوتر  ✦ مدفوعات    ║
╚══════════════════════════════════════════════════════════╝

الوظائف:
  - عرض الرصيد والمديونية لكل خط أعمال
  - سجل المعاملات مع فلترة بالنوع والتاريخ
  - استقبال إشعارات الفواتير الجديدة تلقائياً
  - ربط حساب العميل برقم هاتفه
"""

import logging
import os
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, ConversationHandler
)
from database import Database
from datetime import datetime

# ── إعدادات ──────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS  = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",")]

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)
db  = Database()

# ── حالات المحادثة ────────────────────────────────────────────────────────────
WAIT_PHONE  = 1
WAIT_CODE   = 2
FILTER_DATE = 3

# ── ألوان الخطوط (للإشعارات) ─────────────────────────────────────────────────
BUSINESS_ICONS = {
    "grain":    "🌾",   # حبوب وأعلاف
    "computer": "💻",   # كمبيوتر
    "payments": "💳",   # مدفوعات
}
BUSINESS_NAMES = {
    "grain":    "الحبوب والأعلاف",
    "computer": "الكمبيوتر",
    "payments": "المدفوعات الإلكترونية",
}


# ══════════════════════════════════════════════════════════════════════════════
#  أدوات مساعدة
# ══════════════════════════════════════════════════════════════════════════════

def fmt(amount: float) -> str:
    return f"{amount:,.2f} ج.م"

def get_customer(tg_id: int):
    return db.get_customer_by_telegram_id(tg_id)

def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton("💰 رصيدي ومديونيتي"), KeyboardButton("📋 سجل المعاملات")],
        [KeyboardButton("🌾 الحبوب"),           KeyboardButton("💻 الكمبيوتر")],
        [KeyboardButton("💳 المدفوعات"),         KeyboardButton("📞 تواصل معنا")],
    ]
    if is_admin:
        rows.append([KeyboardButton("⚙️ لوحة الإدارة")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# ══════════════════════════════════════════════════════════════════════════════
#  /start  وربط الحساب
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    customer = get_customer(update.effective_user.id)
    if customer:
        await update.message.reply_text(
            f"مرحباً *{customer['name']}* 👋\n\n"
            f"أهلاً بك في خدمة *عامر جروب*\n"
            f"اختر ما تريد من القائمة أدناه 👇",
            parse_mode="Markdown",
            reply_markup=main_menu(update.effective_user.id in ADMIN_IDS)
        )
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 ربط حسابي الآن", callback_data="link_start")
    ]])
    await update.message.reply_text(
        "👋 أهلاً بك في *بوت عامر جروب*\n\n"
        "يمكنك من خلال هذا البوت:\n"
        "• 💰 متابعة رصيدك ومديونيتك\n"
        "• 📋 عرض سجل معاملاتك\n"
        "• 🔔 استقبال إشعارات الفواتير فوراً\n\n"
        "لبدء الاستخدام، اربط حسابك أولاً:",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ConversationHandler.END


async def link_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "📱 أدخل رقم هاتفك المسجل لدينا:\n_(مثال: 01012345678)_",
        parse_mode="Markdown"
    )
    return WAIT_PHONE


async def link_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip().replace(" ", "").replace("-", "")
    if not (phone.startswith("01") and len(phone) == 11 and phone.isdigit()):
        await update.message.reply_text("❌ رقم غير صحيح. أدخل رقم مصري مكون من 11 رقم.")
        return WAIT_PHONE

    customer = db.get_customer_by_phone(phone)
    if not customer:
        await update.message.reply_text(
            "⚠️ لم يتم العثور على حساب بهذا الرقم.\n"
            "تواصل مع الإدارة لتسجيل حسابك."
        )
        return ConversationHandler.END

    code = db.generate_code(customer['id'])
    ctx.user_data['pending_id'] = customer['id']
    log.info(f"[LINK] Phone {phone} → code {code}")

    await update.message.reply_text(
        f"✅ تم إيجاد حسابك!\n\n"
        f"أُرسل كود التحقق على رقمك.\n"
        f"أدخل الكود المكون من 6 أرقام:\n\n"
        f"_(للتجربة الآن: الكود هو *{code}*)_",
        parse_mode="Markdown"
    )
    return WAIT_CODE


async def link_verify(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    cid  = ctx.user_data.get('pending_id')
    if not cid:
        await update.message.reply_text("❌ انتهت الجلسة. ابدأ من /start")
        return ConversationHandler.END

    if db.verify_code(cid, code):
        db.link_tg(cid, update.effective_user.id)
        customer = db.get_by_id(cid)
        await update.message.reply_text(
            f"🎉 *تم ربط حسابك بنجاح!*\n\nمرحباً *{customer['name']}*",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
    else:
        await update.message.reply_text("❌ الكود غير صحيح أو منتهي الصلاحية.")
        return WAIT_CODE

    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
#  الرصيد الإجمالي (كل الخطوط)
# ══════════════════════════════════════════════════════════════════════════════

async def show_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    customer = get_customer(update.effective_user.id)
    if not customer:
        await update.message.reply_text("⚠️ سجّل دخولك أولاً /start")
        return

    balances = db.get_all_balances(customer['id'])
    total_debt = sum(b['net_debt'] for b in balances.values())

    lines = [
        f"💼 *كشف الرصيد الإجمالي*",
        f"👤 {customer['name']}",
        f"📅 {datetime.now().strftime('%Y/%m/%d  %I:%M %p')}",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    for btype, b in balances.items():
        icon = BUSINESS_ICONS[btype]
        name = BUSINESS_NAMES[btype]
        if b['total_purchases'] == 0 and b['total_payments'] == 0:
            continue
        status = "✅ مسدد" if b['net_debt'] == 0 else f"🔴 {fmt(b['net_debt'])}"
        lines.append(
            f"{icon} *{name}*\n"
            f"   مشتريات: {fmt(b['total_purchases'])}\n"
            f"   مدفوعات: {fmt(b['total_payments'])}\n"
            f"   الرصيد:  {status}"
        )
        lines.append("───────────────────")

    if total_debt == 0:
        summary = "✅ *لا توجد مديونيات — أنت في أمان!*"
    else:
        summary = f"⚠️ *إجمالي المديونية: {fmt(total_debt)}*"

    lines.append(summary)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌾 تفاصيل الحبوب",    callback_data="bal_grain"),
            InlineKeyboardButton("💻 تفاصيل الكمبيوتر", callback_data="bal_computer"),
        ],
        [InlineKeyboardButton("💳 تفاصيل المدفوعات",   callback_data="bal_payments")],
    ])

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=kb
    )


async def balance_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btype    = query.data.split("_")[1]          # grain / computer / payments
    customer = get_customer(query.from_user.id)
    if not customer:
        return

    b    = db.get_balance(customer['id'], btype)
    icon = BUSINESS_ICONS[btype]
    name = BUSINESS_NAMES[btype]
    txns = db.get_transactions(customer['id'], btype, limit=5)

    lines = [
        f"{icon} *{name}*",
        "━━━━━━━━━━━━━━━━━━━",
        f"📦 إجمالي المشتريات: *{fmt(b['total_purchases'])}*",
        f"💳 إجمالي المدفوعات: *{fmt(b['total_payments'])}*",
        f"💼 الرصيد المتبقي:   *{fmt(b['net_debt'])}*",
        "━━━━━━━━━━━━━━━━━━━",
        "*آخر 5 معاملات:*",
    ]
    for t in txns:
        e = "🟢" if t['type'] == 'payment' else "🔴"
        lines.append(f"{e} {t['date']}  {fmt(t['amount'])}  {t['description'][:20]}")

    await query.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  سجل المعاملات
# ══════════════════════════════════════════════════════════════════════════════

async def show_transactions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    customer = get_customer(update.effective_user.id)
    if not customer:
        await update.message.reply_text("⚠️ سجّل دخولك أولاً /start")
        return

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌾 الحبوب",       callback_data="txn_grain"),
            InlineKeyboardButton("💻 الكمبيوتر",    callback_data="txn_computer"),
            InlineKeyboardButton("💳 المدفوعات",    callback_data="txn_payments"),
        ],
        [InlineKeyboardButton("📋 الكل",            callback_data="txn_all")],
    ])
    await update.message.reply_text(
        "📋 *سجل المعاملات*\n\nاختر الخط الذي تريد عرض معاملاته:",
        parse_mode="Markdown",
        reply_markup=kb
    )


async def transactions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btype    = query.data.split("_")[1]
    customer = get_customer(query.from_user.id)
    if not customer:
        return

    if btype == "all":
        txns = db.get_transactions(customer['id'], limit=15)
        title = "📋 جميع المعاملات"
    else:
        txns  = db.get_transactions(customer['id'], btype, limit=15)
        title = f"{BUSINESS_ICONS[btype]} معاملات {BUSINESS_NAMES[btype]}"

    if not txns:
        await query.message.reply_text("📭 لا توجد معاملات.")
        return

    lines = [f"*{title}*\n━━━━━━━━━━━━━━━━━━━"]
    running = 0
    for t in txns:
        if t['type'] == 'purchase':
            running += t['amount']
            lines.append(f"🔴 *شراء*  {fmt(t['amount'])}\n   📅 {t['date']}  |  {t['description']}")
        else:
            running -= t['amount']
            lines.append(f"🟢 *دفع*   {fmt(t['amount'])}\n   📅 {t['date']}  |  {t['description']}")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ أكثر (20 معاملة)", callback_data=f"txnmore_{btype}_20")
    ]])
    await query.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=kb
    )


async def transactions_more_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, btype, limit_str = query.data.split("_")
    limit    = int(limit_str)
    customer = get_customer(query.from_user.id)
    if not customer:
        return

    txns = db.get_transactions(
        customer['id'],
        None if btype == "all" else btype,
        limit=limit
    )
    lines = [f"📋 *آخر {limit} معاملة*\n━━━━━━━━━━━━━━━━━━━"]
    for t in txns:
        e = "🔴" if t['type'] == 'purchase' else "🟢"
        lines.append(f"{e} {t['date']}  {fmt(t['amount'])}  {t['description'][:25]}")

    await query.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  اختصارات الخطوط (أزرار القائمة السريعة)
# ══════════════════════════════════════════════════════════════════════════════

async def show_grain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['quick_btype'] = 'grain'
    await _show_line_balance(update, ctx, 'grain')

async def show_computer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_line_balance(update, ctx, 'computer')

async def show_payments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_line_balance(update, ctx, 'payments')

async def _show_line_balance(update, ctx, btype):
    customer = get_customer(update.effective_user.id)
    if not customer:
        await update.message.reply_text("⚠️ سجّل دخولك أولاً /start")
        return
    b    = db.get_balance(customer['id'], btype)
    icon = BUSINESS_ICONS[btype]
    name = BUSINESS_NAMES[btype]

    debt_line = (
        "✅ لا توجد مديونية" if b['net_debt'] == 0
        else f"🔴 المديونية: *{fmt(b['net_debt'])}*"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📋 سجل المعاملات", callback_data=f"txn_{btype}")
    ]])
    await update.message.reply_text(
        f"{icon} *{name}*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 مشتريات: *{fmt(b['total_purchases'])}*\n"
        f"💳 مدفوعات: *{fmt(b['total_payments'])}*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{debt_line}",
        parse_mode="Markdown",
        reply_markup=kb
    )


# ══════════════════════════════════════════════════════════════════════════════
#  إشعار فاتورة جديدة (يُستدعى برمجياً من API أو من سيستمك مباشرة)
# ══════════════════════════════════════════════════════════════════════════════

async def notify_invoice(app: Application, customer_tg_id: int, data: dict):
    """
    data = {
      'business': 'grain' | 'computer' | 'payments',
      'amount': 9000.0,
      'description': 'قمح - 2 طن',
      'invoice_no': 'INV-001',
      'new_balance': 15000.0,
      'date': '2024/01/15'
    }
    """
    btype = data.get('business', 'grain')
    icon  = BUSINESS_ICONS.get(btype, '🏢')
    name  = BUSINESS_NAMES.get(btype, 'عامر جروب')

    await app.bot.send_message(
        chat_id=customer_tg_id,
        text=(
            f"🔔 *فاتورة جديدة — {name}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{icon} *{data['description']}*\n"
            f"💰 القيمة:     *{fmt(data['amount'])}*\n"
            f"🧾 رقم الفاتورة: `{data['invoice_no']}`\n"
            f"📅 التاريخ:   {data.get('date', datetime.now().strftime('%Y/%m/%d'))}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💼 رصيدك الحالي: *{fmt(data['new_balance'])}*"
        ),
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  لوحة الإدارة
# ══════════════════════════════════════════════════════════════════════════════

async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 تقرير اليوم",         callback_data="adm_today")],
        [InlineKeyboardButton("⚠️ أكبر 10 مديونيات",   callback_data="adm_debts")],
        [InlineKeyboardButton("👥 عدد العملاء المربوطين", callback_data="adm_linked")],
        [InlineKeyboardButton("📢 إشعار جماعي",         callback_data="adm_broadcast")],
    ])
    await update.message.reply_text("⚙️ *لوحة إدارة عامر جروب*", parse_mode="Markdown", reply_markup=kb)


async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        return

    action = query.data.split("_")[1]

    if action == "today":
        r = db.today_report()
        await query.message.reply_text(
            f"📊 *تقرير {datetime.now().strftime('%Y/%m/%d')}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🌾 مبيعات الحبوب:       *{fmt(r['grain_sales'])}*\n"
            f"💻 مبيعات الكمبيوتر:    *{fmt(r['computer_sales'])}*\n"
            f"💳 مبيعات المدفوعات:    *{fmt(r['payments_sales'])}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💵 إجمالي اليوم:        *{fmt(r['total'])}*\n"
            f"🔄 إجمالي المدفوعات:    *{fmt(r['received'])}*",
            parse_mode="Markdown"
        )

    elif action == "debts":
        debtors = db.top_debtors(10)
        lines = ["⚠️ *أكبر 10 مديونيات*\n━━━━━━━━━━━━━━━━━━━"]
        for i, d in enumerate(debtors, 1):
            lines.append(f"{i}. *{d['name']}* — {fmt(d['total_debt'])}")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif action == "linked":
        count = db.linked_count()
        await query.message.reply_text(f"👥 عدد العملاء المربوطين بالبوت: *{count}*", parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  معالج الرسائل العامة
# ══════════════════════════════════════════════════════════════════════════════

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    dispatch = {
        "💰 رصيدي ومديونيتي": show_balance,
        "📋 سجل المعاملات":    show_transactions,
        "🌾 الحبوب":           show_grain,
        "💻 الكمبيوتر":        show_computer,
        "💳 المدفوعات":        show_payments,
        "⚙️ لوحة الإدارة":    admin_panel,
    }
    handler = dispatch.get(text)
    if handler:
        await handler(update, ctx)
    elif text == "📞 تواصل معنا":
        await update.message.reply_text(
            "📞 *تواصل مع عامر جروب*\n\n"
            "🌾 الحبوب والأعلاف:      01xxxxxxxxx\n"
            "💻 الكمبيوتر:             01xxxxxxxxx\n"
            "💳 المدفوعات:             01xxxxxxxxx\n\n"
            "🕐 مواعيد العمل: 8 ص — 8 م",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "اختر من القائمة 👇",
            reply_markup=main_menu(update.effective_user.id in ADMIN_IDS)
        )


# ══════════════════════════════════════════════════════════════════════════════
#  التشغيل
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ربط الحساب
    link_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(link_start, pattern="^link_start$")],
        states={
            WAIT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, link_phone)],
            WAIT_CODE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, link_verify)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(link_conv)

    # Callbacks
    app.add_handler(CallbackQueryHandler(balance_detail_cb,   pattern="^bal_"))
    app.add_handler(CallbackQueryHandler(transactions_cb,     pattern="^txn_[a-z]+$"))
    app.add_handler(CallbackQueryHandler(transactions_more_cb,pattern="^txnmore_"))
    app.add_handler(CallbackQueryHandler(admin_cb,            pattern="^adm_"))

    # رسائل نصية
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("🤖 عامر جروب بوت — جاهز للعمل!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
