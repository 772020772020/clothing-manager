# -*- coding: utf-8 -*-
"""
db.py
طبقة قاعدة البيانات (PostgreSQL / Supabase) لنسخة السحابة.
نفس منطق نسخة SQLite لكن بصيغة PostgreSQL.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from calculations import calc_item

ITEM_STATUSES = [
    "Order Registered", "Purchased From China", "In Transit",
    "Awaiting Weight", "In Warehouse", "Out For Delivery",
    "Delivered", "Delivered Unpaid", "Ready For Sale", "Out of Stock",
]
STATUS_AR = {
    "Order Registered": "تم التسجيل",
    "Purchased From China": "تم الشراء من الصين",
    "In Transit": "في الطريق",
    "Awaiting Weight": "بانتظار الوزن",
    "In Warehouse": "في المستودع",
    "Out For Delivery": "مع شركة الشحن",
    "Delivered": "تم التسليم",
    "Delivered Unpaid": "تسليم - آجل",
    "Ready For Sale": "فوري (للبيع)",
    "Out of Stock": "نفذ من المصدر",
}

# ===== نظام أمريكا (حساب مبسّط: الربح = البيع − التكلفة) =====
USA_STATUSES = ["In Transit", "In Warehouse", "Out For Delivery", "Delivered", "Delivered Unpaid", "Ready For Sale"]
USA_STATUS_AR = {
    "In Transit": "في الطريق",
    "In Warehouse": "في المستودع",
    "Out For Delivery": "مع شركة الشحن",
    "Delivered": "تم التسليم",
    "Delivered Unpaid": "تسليم - آجل",
    "Ready For Sale": "فوري (للبيع)",
}


def connect(cfg):
    """إنشاء اتصال بقاعدة بيانات Supabase."""
    return psycopg2.connect(
        host=cfg["host"],
        port=int(cfg["port"]),
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        cursor_factory=RealDictCursor,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
        connect_timeout=10,
    )


class Database:
    def __init__(self, cfg):
        self.cfg = cfg
        self.conn = connect(cfg)
        self.conn.autocommit = True

    def _cur(self):
        """يرجع cursor، ويعيد الاتصال لو اتقطع."""
        try:
            if self.conn.closed:
                self.conn = connect(self.cfg)
                self.conn.autocommit = True
            return self.conn.cursor()
        except psycopg2.Error:
            self.conn = connect(self.cfg)
            self.conn.autocommit = True
            return self.conn.cursor()

    def _exec(self, sql, params=(), fetch=None):
        """تنفيذ استعلام مع إعادة المحاولة مرة عند انقطاع الاتصال."""
        for attempt in range(2):
            try:
                cur = self._cur()
                cur.execute(sql, params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                if fetch == "id":
                    return cur.fetchone()["id"]
                return None
            except psycopg2.OperationalError:
                if attempt == 0:
                    try:
                        self.conn = connect(self.cfg)
                        self.conn.autocommit = True
                    except psycopg2.Error:
                        pass
                    continue
                raise

    # ---------- أوردرات ----------
    def create_order(self, number, date, buy_rate=0, ship_rate=0, ship_kg=0, notes=""):
        return self._exec(
            """INSERT INTO orders (order_number, order_date, purchase_yuan_rate,
               shipping_yuan_rate, shipping_price_per_kg_yuan, notes)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (number, date, buy_rate, ship_rate, ship_kg, notes), fetch="id")

    def update_order(self, oid, number, date, buy_rate, ship_rate, ship_kg, notes=""):
        self._exec(
            """UPDATE orders SET order_number=%s, order_date=%s, purchase_yuan_rate=%s,
               shipping_yuan_rate=%s, shipping_price_per_kg_yuan=%s, notes=%s WHERE id=%s""",
            (number, date, buy_rate, ship_rate, ship_kg, notes, oid))
        self.recalc_order(oid)

    def delete_order(self, oid):
        self._exec("DELETE FROM orders WHERE id=%s", (oid,))

    def get_order(self, oid):
        return self._exec("SELECT * FROM orders WHERE id=%s", (oid,), fetch="one")

    def all_orders(self):
        # ترتيب بالرقم تنازلياً (الأكبر فوق)؛ لو الرقم مش رقمي يترتب نصياً في الآخر
        return self._exec("""
            SELECT * FROM orders
            ORDER BY
                CASE WHEN order_number ~ '^[0-9]+$' THEN 0 ELSE 1 END,
                CASE WHEN order_number ~ '^[0-9]+$' THEN CAST(order_number AS BIGINT) ELSE NULL END DESC,
                order_number DESC
        """, fetch="all")

    def order_summary(self, oid):
        return self._exec("""
            SELECT COUNT(*) pieces,
                COALESCE(SUM(CASE WHEN weight_grams>0 THEN 1 ELSE 0 END),0) with_weight,
                COALESCE(SUM(CASE WHEN weight_grams<=0 THEN 1 ELSE 0 END),0) awaiting_weight,
                COALESCE(SUM(CASE WHEN status='Delivered' THEN 1 ELSE 0 END),0) delivered,
                COALESCE(SUM(weight_grams),0) total_weight,
                COALESCE(SUM(selling_price_egp),0) sales,
                COALESCE(SUM(deposit_paid),0) deposits,
                COALESCE(SUM(selling_price_egp-deposit_paid),0) balance,
                COALESCE(SUM(CASE WHEN weight_grams>0 THEN total_cost_egp ELSE 0 END),0) cost,
                COALESCE(SUM(CASE WHEN weight_grams>0 THEN profit_egp ELSE 0 END),0) profit
            FROM items WHERE order_id=%s AND status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
        """, (oid,), fetch="one")

    # ---------- قطع ----------
    def _compute(self, oid, buy_yuan, weight_g, sell):
        o = self.get_order(oid)
        return calc_item(buy_yuan, weight_g, sell, o["purchase_yuan_rate"],
                         o["shipping_yuan_rate"], o["shipping_price_per_kg_yuan"])

    def create_item(self, oid, customer, product, sell, buy_yuan, weight_g=0, deposit=0,
                    status="Order Registered", weight_date=None):
        c = self._compute(oid, buy_yuan, weight_g, sell)
        return self._exec(
            """INSERT INTO items (order_id, customer_name, product_name, selling_price_egp,
               purchase_price_yuan, weight_grams, deposit_paid, status,
               purchase_cost_egp, shipping_cost_egp, total_cost_egp, profit_egp, weight_date)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (oid, customer, product, sell, buy_yuan, weight_g, deposit, status,
             c["purchase_cost_egp"], c["shipping_cost_egp"], c["total_cost_egp"], c["profit_egp"], weight_date),
            fetch="id")

    def update_item(self, iid, customer, product, sell, buy_yuan, weight_g=0, deposit=0,
                    status="Order Registered", weight_date=None):
        it = self.get_item(iid)
        c = self._compute(it["order_id"], buy_yuan, weight_g, sell)
        self._exec(
            """UPDATE items SET customer_name=%s, product_name=%s, selling_price_egp=%s,
               purchase_price_yuan=%s, weight_grams=%s, deposit_paid=%s, status=%s,
               purchase_cost_egp=%s, shipping_cost_egp=%s, total_cost_egp=%s, profit_egp=%s, weight_date=%s
               WHERE id=%s""",
            (customer, product, sell, buy_yuan, weight_g, deposit, status,
             c["purchase_cost_egp"], c["shipping_cost_egp"], c["total_cost_egp"], c["profit_egp"], weight_date, iid))

    def update_item_status(self, iid, status):
        """تحديث حالة القطعة فقط (للوحة المعلومات)."""
        self._exec("UPDATE items SET status=%s WHERE id=%s", (status, iid))

    def items_by_status(self, status):
        """كل القطع في حالة معيّنة مع رقم الأوردر."""
        return self._exec("""SELECT i.*, o.order_number FROM items i
            JOIN orders o ON o.id=i.order_id
            WHERE i.status=%s
            ORDER BY o.order_date::date DESC, o.id DESC, i.id ASC""", (status,), fetch="all")

    def status_counts(self):
        """عدد القطع في كل حالة."""
        rows = self._exec("SELECT status, COUNT(*) c FROM items GROUP BY status", fetch="all")
        return {r["status"]: r["c"] for r in rows}

    def all_items_with_order(self):
        """كل القطع مع رقم الأوردر (للوحة المعلومات والتعديل السريع)."""
        return self._exec("""SELECT i.*, o.order_number FROM items i
            JOIN orders o ON o.id=i.order_id
            ORDER BY o.order_date::date DESC, o.id DESC, i.id ASC""", fetch="all")

    def items_by_weight_date(self, day):
        """القطع اللي اتسجّل وزنها في يوم معين + أرباحها (بدون الملغي)."""
        return self._exec("""SELECT i.*, o.order_number FROM items i
            JOIN orders o ON o.id=i.order_id
            WHERE i.weight_date=%s AND i.weight_grams>0
              AND i.status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
            ORDER BY o.order_number, i.id""", (day,), fetch="all")

    def items_of_customer(self, customer):
        """كل قطع عميل معين."""
        return self._exec("""SELECT i.*, o.order_number FROM items i
            JOIN orders o ON o.id=i.order_id
            WHERE i.customer_name=%s
            ORDER BY o.order_date::date DESC, i.id ASC""", (customer,), fetch="all")

    def weight_dates(self):
        """كل التواريخ اللي فيها قطع اتسجّل وزنها (للاختيار)."""
        rows = self._exec("""SELECT DISTINCT weight_date FROM items
            WHERE weight_date IS NOT NULL AND weight_grams>0
            ORDER BY weight_date DESC""", fetch="all")
        return [r["weight_date"] for r in rows]

    def customers_list(self):
        rows = self._exec("SELECT DISTINCT customer_name FROM items ORDER BY customer_name", fetch="all")
        return [r["customer_name"] for r in rows]

    def delete_item(self, iid):
        self._exec("DELETE FROM items WHERE id=%s", (iid,))

    def get_item(self, iid):
        return self._exec("SELECT * FROM items WHERE id=%s", (iid,), fetch="one")

    def items_of(self, oid):
        return self._exec("SELECT * FROM items WHERE order_id=%s ORDER BY id ASC", (oid,), fetch="all")

    def recalc_order(self, oid):
        o = self.get_order(oid)
        if not o:
            return
        for it in self.items_of(oid):
            c = calc_item(it["purchase_price_yuan"], it["weight_grams"], it["selling_price_egp"],
                          o["purchase_yuan_rate"], o["shipping_yuan_rate"], o["shipping_price_per_kg_yuan"])
            self._exec(
                """UPDATE items SET purchase_cost_egp=%s, shipping_cost_egp=%s,
                   total_cost_egp=%s, profit_egp=%s WHERE id=%s""",
                (c["purchase_cost_egp"], c["shipping_cost_egp"], c["total_cost_egp"], c["profit_egp"], it["id"]))

    # ---------- لوحة المعلومات ----------
    def dashboard(self):
        orders = self._exec("SELECT COUNT(*) c FROM orders", fetch="one")["c"]
        total_pieces = self._exec("SELECT COUNT(*) c FROM items", fetch="one")["c"]
        r = self._exec("""
            SELECT
                COALESCE(SUM(CASE WHEN weight_grams<=0 THEN 1 ELSE 0 END),0) awaiting,
                COALESCE(SUM(selling_price_egp),0) sales,
                COALESCE(SUM(CASE WHEN weight_grams>0 THEN total_cost_egp ELSE 0 END),0) cost,
                COALESCE(SUM(CASE WHEN weight_grams>0 THEN profit_egp ELSE 0 END),0) profit,
                COALESCE(SUM(CASE WHEN status <> 'Delivered'
                    THEN selling_price_egp-deposit_paid ELSE 0 END),0) outstanding
            FROM items WHERE status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
        """, fetch="one")
        # الربح المتوقع للقطع التي لم يصلها وزن بعد (تقدير وزن 500 جرام)
        ep = self._exec("""
            SELECT COALESCE(SUM(
                i.selling_price_egp - (
                    i.purchase_price_yuan * o.purchase_yuan_rate
                    + 0.5 * o.shipping_price_per_kg_yuan * o.shipping_yuan_rate
                )
            ),0) expected
            FROM items i JOIN orders o ON o.id=i.order_id
            WHERE i.weight_grams<=0
              AND i.status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
        """, fetch="one")
        sc_rows = self._exec("SELECT status, COUNT(*) c FROM items GROUP BY status", fetch="all")
        sc = {row["status"]: row["c"] for row in sc_rows}
        return {
            "orders": orders, "pieces": total_pieces, "awaiting": r["awaiting"] or 0,
            "sales": r["sales"], "cost": r["cost"], "profit": r["profit"],
            "outstanding": r["outstanding"], "expected_profit": ep["expected"],
            "in_transit": sc.get("In Transit", 0), "in_warehouse": sc.get("In Warehouse", 0),
            "delivered": sc.get("Delivered", 0),
        }

    def weight_dates_with_counts(self):
        """أيام الوصول (تسجيل الوزن) مع عدد القطع في كل يوم — للقائمة السريعة."""
        return self._exec("""SELECT weight_date, COUNT(*) c FROM items
            WHERE weight_date IS NOT NULL AND weight_grams>0
              AND status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
            GROUP BY weight_date ORDER BY weight_date DESC""", fetch="all")

    # ---------- تقارير ----------
    def report_by_order(self):
        return self._exec("""SELECT o.order_number, o.order_date, COUNT(i.id) pieces,
            COALESCE(SUM(i.purchase_price_yuan),0) yuan_total,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.total_cost_egp ELSE 0 END),0) cost,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.profit_egp ELSE 0 END),0) profit
            FROM orders o LEFT JOIN items i ON i.order_id=o.id
                AND i.status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
            GROUP BY o.id ORDER BY o.order_date::date DESC, o.id DESC""", fetch="all")

    def report_by_customer(self):
        return self._exec("""SELECT customer_name, COUNT(*) pieces,
            COALESCE(SUM(purchase_price_yuan),0) yuan_total,
            COALESCE(SUM(selling_price_egp),0) sales,
            COALESCE(SUM(deposit_paid),0) deposits,
            COALESCE(SUM(selling_price_egp-deposit_paid),0) balance,
            COALESCE(SUM(CASE WHEN weight_grams>0 THEN profit_egp ELSE 0 END),0) profit
            FROM items WHERE status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
            GROUP BY customer_name ORDER BY profit DESC""", fetch="all")

    def report_monthly(self):
        return self._exec("""SELECT TO_CHAR(o.order_date::date,'YYYY-MM') period, COUNT(i.id) pieces,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.total_cost_egp ELSE 0 END),0) cost,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.profit_egp ELSE 0 END),0) profit
            FROM orders o LEFT JOIN items i ON i.order_id=o.id
                AND i.status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
            GROUP BY period ORDER BY period DESC""", fetch="all")

    def report_yearly(self):
        return self._exec("""SELECT TO_CHAR(o.order_date::date,'YYYY') period, COUNT(i.id) pieces,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.total_cost_egp ELSE 0 END),0) cost,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.profit_egp ELSE 0 END),0) profit
            FROM orders o LEFT JOIN items i ON i.order_id=o.id
                AND i.status NOT IN ('Out of Stock','Cancelled','Ready For Sale')
            GROUP BY period ORDER BY period DESC""", fetch="all")

    def all_items_detailed(self):
        return self._exec("""SELECT o.order_number, o.order_date, i.customer_name, i.product_name,
            i.selling_price_egp, i.purchase_price_yuan, i.weight_grams, i.deposit_paid, i.status,
            i.purchase_cost_egp, i.shipping_cost_egp, i.total_cost_egp, i.profit_egp
            FROM items i JOIN orders o ON o.id=i.order_id
            ORDER BY o.order_date::date DESC, o.id DESC, i.id ASC""", fetch="all")

    # ============================================================
    #  نظام أمريكا (جداول منفصلة، حساب مبسّط)
    # ============================================================
    def usa_init(self):
        """إنشاء جداول أمريكا لو مش موجودة."""
        self._exec("""CREATE TABLE IF NOT EXISTS usa_orders (
            id SERIAL PRIMARY KEY,
            order_number TEXT NOT NULL,
            order_date TEXT NOT NULL,
            supplier_name TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        )""")
        self._exec("""CREATE TABLE IF NOT EXISTS usa_items (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES usa_orders(id) ON DELETE CASCADE,
            customer_name TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            cost_egp DOUBLE PRECISION DEFAULT 0,
            selling_price_egp DOUBLE PRECISION DEFAULT 0,
            deposit_paid DOUBLE PRECISION DEFAULT 0,
            profit_egp DOUBLE PRECISION DEFAULT 0,
            status TEXT DEFAULT 'In Transit'
        )""")
        # جدول المصاريف العامة (تخص الصين وأمريكا معاً)
        self._exec("""CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            exp_date TEXT NOT NULL,
            name TEXT DEFAULT '',
            amount DOUBLE PRECISION DEFAULT 0,
            notes TEXT DEFAULT ''
        )""")

    # ---------- المصاريف العامة ----------
    def add_expense(self, exp_date, name, amount, notes=""):
        return self._exec(
            "INSERT INTO expenses (exp_date, name, amount, notes) VALUES (%s,%s,%s,%s) RETURNING id",
            (exp_date, name, amount, notes), fetch="id")

    def delete_expense(self, eid):
        self._exec("DELETE FROM expenses WHERE id=%s", (eid,))

    def all_expenses(self):
        return self._exec("SELECT * FROM expenses ORDER BY exp_date::date DESC, id DESC", fetch="all")

    def expenses_total(self):
        r = self._exec("SELECT COALESCE(SUM(amount),0) t FROM expenses", fetch="one")
        return r["t"] if r else 0

    def expenses_by_month(self):
        return self._exec("""SELECT TO_CHAR(exp_date::date,'YYYY-MM') period,
            COALESCE(SUM(amount),0) total FROM expenses GROUP BY period""", fetch="all")

    def expenses_by_year(self):
        return self._exec("""SELECT TO_CHAR(exp_date::date,'YYYY') period,
            COALESCE(SUM(amount),0) total FROM expenses GROUP BY period""", fetch="all")

    # ---------- أوردرات أمريكا ----------
    def usa_create_order(self, number, date, supplier="", notes=""):
        return self._exec(
            """INSERT INTO usa_orders (order_number, order_date, supplier_name, notes)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (number, date, supplier, notes), fetch="id")

    def usa_update_order(self, oid, number, date, supplier, notes=""):
        self._exec(
            """UPDATE usa_orders SET order_number=%s, order_date=%s, supplier_name=%s, notes=%s
               WHERE id=%s""",
            (number, date, supplier, notes, oid))

    def usa_delete_order(self, oid):
        self._exec("DELETE FROM usa_orders WHERE id=%s", (oid,))

    def usa_get_order(self, oid):
        return self._exec("SELECT * FROM usa_orders WHERE id=%s", (oid,), fetch="one")

    def usa_all_orders(self):
        return self._exec("""
            SELECT * FROM usa_orders
            ORDER BY
                CASE WHEN order_number ~ '^[0-9]+$' THEN 0 ELSE 1 END,
                CASE WHEN order_number ~ '^[0-9]+$' THEN CAST(order_number AS BIGINT) ELSE NULL END DESC,
                order_number DESC
        """, fetch="all")

    def usa_order_summary(self, oid):
        return self._exec("""
            SELECT COUNT(*) pieces,
                COALESCE(SUM(CASE WHEN status='Delivered' THEN 1 ELSE 0 END),0) delivered,
                COALESCE(SUM(selling_price_egp),0) sales,
                COALESCE(SUM(cost_egp),0) cost,
                COALESCE(SUM(deposit_paid),0) deposits,
                COALESCE(SUM(selling_price_egp-deposit_paid),0) balance,
                COALESCE(SUM(profit_egp),0) profit
            FROM usa_items WHERE order_id=%s AND status <> 'Ready For Sale'
        """, (oid,), fetch="one")

    # ---------- قطع أمريكا ----------
    def usa_add_item(self, order_id, customer, product, cost, sell, deposit, status="In Transit"):
        profit = (sell or 0) - (cost or 0)
        return self._exec(
            """INSERT INTO usa_items (order_id, customer_name, product_name, cost_egp,
               selling_price_egp, deposit_paid, profit_egp, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (order_id, customer, product, cost, sell, deposit, profit, status), fetch="id")

    def usa_update_item(self, item_id, customer, product, cost, sell, deposit, status):
        profit = (sell or 0) - (cost or 0)
        self._exec(
            """UPDATE usa_items SET customer_name=%s, product_name=%s, cost_egp=%s,
               selling_price_egp=%s, deposit_paid=%s, profit_egp=%s, status=%s WHERE id=%s""",
            (customer, product, cost, sell, deposit, profit, status, item_id))

    def usa_delete_item(self, item_id):
        self._exec("DELETE FROM usa_items WHERE id=%s", (item_id,))

    def usa_update_item_status(self, item_id, status):
        self._exec("UPDATE usa_items SET status=%s WHERE id=%s", (status, item_id))

    def usa_items_by_status(self, status):
        """كل قطع أمريكا في حالة معيّنة مع رقم الأوردر والمورد."""
        return self._exec("""SELECT i.*, o.order_number, o.supplier_name FROM usa_items i
            JOIN usa_orders o ON o.id=i.order_id
            WHERE i.status=%s
            ORDER BY o.order_date::date DESC, o.id DESC, i.id ASC""", (status,), fetch="all")

    def usa_status_counts(self):
        rows = self._exec("SELECT status, COUNT(*) c FROM usa_items GROUP BY status", fetch="all")
        return {r["status"]: r["c"] for r in rows}

    def usa_items_of(self, order_id):
        return self._exec("SELECT * FROM usa_items WHERE order_id=%s ORDER BY id ASC",
                          (order_id,), fetch="all")

    def usa_all_items_detailed(self):
        return self._exec("""SELECT o.order_number, o.supplier_name, o.order_date,
            i.customer_name, i.product_name, i.cost_egp, i.selling_price_egp,
            i.deposit_paid, i.profit_egp, i.status
            FROM usa_items i JOIN usa_orders o ON o.id=i.order_id
            ORDER BY o.order_date::date DESC, o.id DESC, i.id ASC""", fetch="all")

    def usa_items_of_customer(self, name):
        return self._exec("""SELECT i.*, o.order_number, o.supplier_name FROM usa_items i
            JOIN usa_orders o ON o.id=i.order_id
            WHERE i.customer_name=%s ORDER BY o.id DESC, i.id ASC""", (name,), fetch="all")

    def usa_customers_list(self):
        rows = self._exec("""SELECT DISTINCT customer_name FROM usa_items
            WHERE customer_name<>'' ORDER BY customer_name""", fetch="all")
        return [r["customer_name"] for r in rows]

    # ---------- لوحة معلومات أمريكا ----------
    def usa_dashboard(self):
        orders = self._exec("SELECT COUNT(*) c FROM usa_orders", fetch="one")["c"]
        total_pieces = self._exec("SELECT COUNT(*) c FROM usa_items", fetch="one")["c"]
        r = self._exec("""
            SELECT
                COALESCE(SUM(selling_price_egp),0) sales,
                COALESCE(SUM(cost_egp),0) cost,
                COALESCE(SUM(profit_egp),0) profit,
                COALESCE(SUM(CASE WHEN status <> 'Delivered'
                    THEN selling_price_egp-deposit_paid ELSE 0 END),0) outstanding
            FROM usa_items WHERE status <> 'Ready For Sale'
        """, fetch="one")
        return {
            "orders": orders, "pieces": total_pieces, "sales": r["sales"],
            "cost": r["cost"], "profit": r["profit"], "outstanding": r["outstanding"],
        }

    # ---------- تقارير أمريكا ----------
    def usa_report_by_order(self):
        return self._exec("""SELECT o.order_number, o.order_date, o.supplier_name, COUNT(i.id) pieces,
            COALESCE(SUM(i.cost_egp),0) cost,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(i.profit_egp),0) profit
            FROM usa_orders o LEFT JOIN usa_items i ON i.order_id=o.id
                AND i.status <> 'Ready For Sale'
            GROUP BY o.id ORDER BY o.order_date::date DESC, o.id DESC""", fetch="all")

    def usa_report_by_customer(self):
        return self._exec("""SELECT customer_name, COUNT(*) pieces,
            COALESCE(SUM(cost_egp),0) cost,
            COALESCE(SUM(selling_price_egp),0) sales,
            COALESCE(SUM(deposit_paid),0) deposits,
            COALESCE(SUM(selling_price_egp-deposit_paid),0) balance,
            COALESCE(SUM(profit_egp),0) profit
            FROM usa_items WHERE status <> 'Ready For Sale'
            GROUP BY customer_name ORDER BY profit DESC""", fetch="all")

    def usa_report_monthly(self):
        return self._exec("""SELECT TO_CHAR(o.order_date::date,'YYYY-MM') period, COUNT(i.id) pieces,
            COALESCE(SUM(i.cost_egp),0) cost,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(i.profit_egp),0) profit
            FROM usa_orders o LEFT JOIN usa_items i ON i.order_id=o.id
                AND i.status <> 'Ready For Sale'
            GROUP BY period ORDER BY period DESC""", fetch="all")

    def usa_report_yearly(self):
        return self._exec("""SELECT TO_CHAR(o.order_date::date,'YYYY') period, COUNT(i.id) pieces,
            COALESCE(SUM(i.cost_egp),0) cost,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(i.profit_egp),0) profit
            FROM usa_orders o LEFT JOIN usa_items i ON i.order_id=o.id
                AND i.status <> 'Ready For Sale'
            GROUP BY period ORDER BY period DESC""", fetch="all")
