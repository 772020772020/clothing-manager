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
    "Delivered", "Cancelled",
]
STATUS_AR = {
    "Order Registered": "تم التسجيل",
    "Purchased From China": "تم الشراء من الصين",
    "In Transit": "في الطريق",
    "Awaiting Weight": "بانتظار الوزن",
    "In Warehouse": "في المستودع",
    "Out For Delivery": "خرج للتسليم",
    "Delivered": "تم التسليم",
    "Cancelled": "ملغي",
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
        return self._exec("SELECT * FROM orders ORDER BY order_date::date DESC, id DESC", fetch="all")

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
            FROM items WHERE order_id=%s
        """, (oid,), fetch="one")

    # ---------- قطع ----------
    def _compute(self, oid, buy_yuan, weight_g, sell):
        o = self.get_order(oid)
        return calc_item(buy_yuan, weight_g, sell, o["purchase_yuan_rate"],
                         o["shipping_yuan_rate"], o["shipping_price_per_kg_yuan"])

    def create_item(self, oid, customer, product, sell, buy_yuan, weight_g=0, deposit=0, status="Order Registered"):
        c = self._compute(oid, buy_yuan, weight_g, sell)
        return self._exec(
            """INSERT INTO items (order_id, customer_name, product_name, selling_price_egp,
               purchase_price_yuan, weight_grams, deposit_paid, status,
               purchase_cost_egp, shipping_cost_egp, total_cost_egp, profit_egp)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (oid, customer, product, sell, buy_yuan, weight_g, deposit, status,
             c["purchase_cost_egp"], c["shipping_cost_egp"], c["total_cost_egp"], c["profit_egp"]),
            fetch="id")

    def update_item(self, iid, customer, product, sell, buy_yuan, weight_g=0, deposit=0, status="Order Registered"):
        it = self.get_item(iid)
        c = self._compute(it["order_id"], buy_yuan, weight_g, sell)
        self._exec(
            """UPDATE items SET customer_name=%s, product_name=%s, selling_price_egp=%s,
               purchase_price_yuan=%s, weight_grams=%s, deposit_paid=%s, status=%s,
               purchase_cost_egp=%s, shipping_cost_egp=%s, total_cost_egp=%s, profit_egp=%s
               WHERE id=%s""",
            (customer, product, sell, buy_yuan, weight_g, deposit, status,
             c["purchase_cost_egp"], c["shipping_cost_egp"], c["total_cost_egp"], c["profit_egp"], iid))

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
        r = self._exec("""
            SELECT COUNT(*) pieces,
                COALESCE(SUM(CASE WHEN weight_grams<=0 THEN 1 ELSE 0 END),0) awaiting,
                COALESCE(SUM(selling_price_egp),0) sales,
                COALESCE(SUM(CASE WHEN weight_grams>0 THEN total_cost_egp ELSE 0 END),0) cost,
                COALESCE(SUM(CASE WHEN weight_grams>0 THEN profit_egp ELSE 0 END),0) profit,
                COALESCE(SUM(selling_price_egp-deposit_paid),0) outstanding
            FROM items
        """, fetch="one")
        sc_rows = self._exec("SELECT status, COUNT(*) c FROM items GROUP BY status", fetch="all")
        sc = {row["status"]: row["c"] for row in sc_rows}
        return {
            "orders": orders, "pieces": r["pieces"], "awaiting": r["awaiting"] or 0,
            "sales": r["sales"], "cost": r["cost"], "profit": r["profit"],
            "outstanding": r["outstanding"],
            "in_transit": sc.get("In Transit", 0), "in_warehouse": sc.get("In Warehouse", 0),
            "delivered": sc.get("Delivered", 0),
        }

    # ---------- تقارير ----------
    def report_by_order(self):
        return self._exec("""SELECT o.order_number, o.order_date, COUNT(i.id) pieces,
            COALESCE(SUM(i.purchase_price_yuan),0) yuan_total,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.total_cost_egp ELSE 0 END),0) cost,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.profit_egp ELSE 0 END),0) profit
            FROM orders o LEFT JOIN items i ON i.order_id=o.id
            GROUP BY o.id ORDER BY o.order_date::date DESC, o.id DESC""", fetch="all")

    def report_by_customer(self):
        return self._exec("""SELECT customer_name, COUNT(*) pieces,
            COALESCE(SUM(selling_price_egp),0) sales,
            COALESCE(SUM(deposit_paid),0) deposits,
            COALESCE(SUM(selling_price_egp-deposit_paid),0) balance,
            COALESCE(SUM(CASE WHEN weight_grams>0 THEN profit_egp ELSE 0 END),0) profit
            FROM items GROUP BY customer_name ORDER BY profit DESC""", fetch="all")

    def report_monthly(self):
        return self._exec("""SELECT TO_CHAR(o.order_date::date,'YYYY-MM') period, COUNT(i.id) pieces,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.total_cost_egp ELSE 0 END),0) cost,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.profit_egp ELSE 0 END),0) profit
            FROM orders o LEFT JOIN items i ON i.order_id=o.id
            GROUP BY period ORDER BY period DESC""", fetch="all")

    def report_yearly(self):
        return self._exec("""SELECT TO_CHAR(o.order_date::date,'YYYY') period, COUNT(i.id) pieces,
            COALESCE(SUM(i.selling_price_egp),0) sales,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.total_cost_egp ELSE 0 END),0) cost,
            COALESCE(SUM(CASE WHEN i.weight_grams>0 THEN i.profit_egp ELSE 0 END),0) profit
            FROM orders o LEFT JOIN items i ON i.order_id=o.id
            GROUP BY period ORDER BY period DESC""", fetch="all")

    def all_items_detailed(self):
        return self._exec("""SELECT o.order_number, o.order_date, i.customer_name, i.product_name,
            i.selling_price_egp, i.purchase_price_yuan, i.weight_grams, i.deposit_paid, i.status,
            i.purchase_cost_egp, i.shipping_cost_egp, i.total_cost_egp, i.profit_egp
            FROM items i JOIN orders o ON o.id=i.order_id
            ORDER BY o.order_date::date DESC, o.id DESC, i.id ASC""", fetch="all")
