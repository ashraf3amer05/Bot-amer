"""
قاعدة البيانات — عامر جروب (3 خطوط)
Database — Amer Group (3 Business Lines)
"""

import sqlite3
import random
import string
from datetime import datetime, timedelta
from typing import Optional, List, Dict


class Database:
    def __init__(self, path: str = "amer_group.db"):
        self.path = path
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    # ─── إنشاء الجداول ───────────────────────────────────────────────────────

    def _init(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS customers (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL,
                    phone         TEXT    UNIQUE NOT NULL,
                    telegram_id   INTEGER UNIQUE,
                    is_active     INTEGER DEFAULT 1,
                    created_at    TEXT    DEFAULT (datetime('now','localtime'))
                );

                -- معاملات موحدة مع عمود business لتمييز الخط
                CREATE TABLE IF NOT EXISTS transactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    business    TEXT    NOT NULL CHECK(business IN ('grain','computer','payments')),
                    type        TEXT    NOT NULL CHECK(type IN ('purchase','payment')),
                    amount      REAL    NOT NULL,
                    description TEXT,
                    invoice_no  TEXT,
                    created_at  TEXT    DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS verification_codes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    code        TEXT    NOT NULL,
                    expires_at  TEXT    NOT NULL,
                    used        INTEGER DEFAULT 0
                );

                -- ── بيانات تجريبية ────────────────────────────────────────
                INSERT OR IGNORE INTO customers (id, name, phone) VALUES
                    (1, 'أحمد محمد السيد',   '01012345678'),
                    (2, 'محمود علي حسن',     '01098765432'),
                    (3, 'سامي عبد الرحمن',   '01155544433');

                INSERT OR IGNORE INTO transactions
                    (id, customer_id, business, type, amount, description, invoice_no) VALUES
                -- أحمد - حبوب
                (1,  1, 'grain',    'purchase', 9000,  'قمح - 2 طن',       'G-001'),
                (2,  1, 'grain',    'purchase', 7600,  'ذرة - 2 طن',       'G-002'),
                (3,  1, 'grain',    'payment',  5000,  'دفعة نقدية',        NULL),
                (4,  1, 'grain',    'purchase', 14400, 'كسب صويا - 2 طن',  'G-003'),
                (5,  1, 'grain',    'payment',  8000,  'تحويل بنكي',        NULL),
                -- أحمد - كمبيوتر
                (6,  1, 'computer', 'purchase', 3500,  'لابتوب HP',         'C-001'),
                (7,  1, 'computer', 'payment',  1500,  'دفعة أولى',         NULL),
                -- أحمد - مدفوعات
                (8,  1, 'payments', 'purchase', 200,   'شحن فودافون كاش',   'P-001'),
                (9,  1, 'payments', 'payment',  200,   'سداد',               NULL),
                -- محمود - حبوب
                (10, 2, 'grain',    'purchase', 22500, 'أعلاف دواجن - 5 طن','G-010'),
                (11, 2, 'grain',    'payment',  10000, 'دفعة نقدية',         NULL);
            """)

    # ─── العملاء ─────────────────────────────────────────────────────────────

    def get_customer_by_telegram_id(self, tg_id: int) -> Optional[Dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM customers WHERE telegram_id=? AND is_active=1", (tg_id,)).fetchone()
            return dict(r) if r else None

    def get_customer_by_phone(self, phone: str) -> Optional[Dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM customers WHERE phone=? AND is_active=1", (phone,)).fetchone()
            return dict(r) if r else None

    def get_by_id(self, cid: int) -> Optional[Dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
            return dict(r) if r else None

    def link_tg(self, cid: int, tg_id: int):
        with self._conn() as c:
            c.execute("UPDATE customers SET telegram_id=? WHERE id=?", (tg_id, cid))

    def linked_count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM customers WHERE telegram_id IS NOT NULL").fetchone()[0]

    # ─── التحقق ──────────────────────────────────────────────────────────────

    def generate_code(self, cid: int) -> str:
        code = "".join(random.choices(string.digits, k=6))
        exp  = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as c:
            c.execute("DELETE FROM verification_codes WHERE customer_id=?", (cid,))
            c.execute("INSERT INTO verification_codes (customer_id,code,expires_at) VALUES (?,?,?)", (cid, code, exp))
        return code

    def verify_code(self, cid: int, code: str) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT id FROM verification_codes WHERE customer_id=? AND code=? AND used=0 AND expires_at>datetime('now','localtime')",
                (cid, code)
            ).fetchone()
            if r:
                c.execute("UPDATE verification_codes SET used=1 WHERE id=?", (r["id"],))
                return True
        return False

    # ─── الأرصدة ─────────────────────────────────────────────────────────────

    def get_balance(self, cid: int, business: str) -> Dict:
        with self._conn() as c:
            r = c.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN type='purchase' THEN amount ELSE 0 END),0) AS purchases,
                    COALESCE(SUM(CASE WHEN type='payment'  THEN amount ELSE 0 END),0) AS payments
                FROM transactions WHERE customer_id=? AND business=?
            """, (cid, business)).fetchone()
        p, pay = r["purchases"], r["payments"]
        return {"total_purchases": p, "total_payments": pay, "net_debt": p - pay}

    def get_all_balances(self, cid: int) -> Dict[str, Dict]:
        return {b: self.get_balance(cid, b) for b in ("grain", "computer", "payments")}

    # ─── المعاملات ───────────────────────────────────────────────────────────

    def get_transactions(self, cid: int, business: str = None, limit: int = 10) -> List[Dict]:
        sql = "SELECT * FROM transactions WHERE customer_id=?"
        args = [cid]
        if business:
            sql += " AND business=?"
            args.append(business)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d['date'] = d['created_at'][:10]
            result.append(d)
        return result

    def add_transaction(self, cid: int, business: str, ttype: str,
                        amount: float, description: str, invoice_no: str = None) -> int:
        """يُستدعى من السيستم أو الـ API عند تسجيل معاملة جديدة"""
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO transactions (customer_id,business,type,amount,description,invoice_no) VALUES (?,?,?,?,?,?)",
                (cid, business, ttype, amount, description, invoice_no)
            )
            return cur.lastrowid

    # ─── الإدارة ─────────────────────────────────────────────────────────────

    def today_report(self) -> Dict:
        today = datetime.now().strftime("%Y-%m-%d")
        with self._conn() as c:
            def sales(biz):
                return c.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='purchase' AND business=? AND date(created_at)=?",
                    (biz, today)
                ).fetchone()[0]
            def received():
                return c.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='payment' AND date(created_at)=?",
                    (today,)
                ).fetchone()[0]
            g, comp, pay = sales("grain"), sales("computer"), sales("payments")
            return {
                "grain_sales":    g,
                "computer_sales": comp,
                "payments_sales": pay,
                "total":          g + comp + pay,
                "received":       received(),
            }

    def top_debtors(self, n: int = 10) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT
                    cu.name,
                    cu.phone,
                    COALESCE(SUM(CASE WHEN t.type='purchase' THEN t.amount ELSE -t.amount END),0) AS total_debt
                FROM customers cu
                LEFT JOIN transactions t ON t.customer_id = cu.id
                WHERE cu.is_active=1
                GROUP BY cu.id
                HAVING total_debt > 0
                ORDER BY total_debt DESC
                LIMIT ?
            """, (n,)).fetchall()
        return [dict(r) for r in rows]
