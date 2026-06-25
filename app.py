# -*- coding: utf-8 -*-
"""
app.py
نسخة الويب من برنامج إدارة تجارة الملابس المستوردة (Streamlit).
التشغيل:  streamlit run app.py
"""

import io
from datetime import date
import pandas as pd
import streamlit as st

from db import Database, ITEM_STATUSES, STATUS_AR
from calculations import calc_item, payment_status, remaining_balance

# ============================================================
#  إعداد الصفحة + RTL
# ============================================================
st.set_page_config(page_title="إدارة الملابس المستوردة", page_icon="🧵",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .stApp { direction: rtl; }
    section[data-testid="stSidebar"] { direction: rtl; }
    h1, h2, h3, h4, h5, h6, p, label, div, span { text-align: right; }
    .stDataFrame { direction: ltr; }
    [data-testid="stMetricValue"] { direction: ltr; text-align: center; }
    [data-testid="stMetricLabel"] { justify-content: center; }
    .stButton button { width: 100%; }
    /* تحسين العرض على الموبايل */
    @media (max-width: 640px) {
        [data-testid="stMetricValue"] { font-size: 1.4rem; }
        h1 { font-size: 1.5rem; }
        h2 { font-size: 1.3rem; }
        h3 { font-size: 1.1rem; }
        .block-container { padding-top: 2.5rem; padding-left: 1rem; padding-right: 1rem; }
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
#  اتصال قاعدة البيانات Supabase (cached)
# ============================================================
@st.cache_resource
def get_db():
    cfg = dict(st.secrets["postgres"])
    return Database(cfg)

db = get_db()


def egp(v):
    try:
        return f"{float(v):,.2f} ج.م"
    except (TypeError, ValueError):
        return "0.00 ج.م"


def rerun():
    st.rerun()


# ============================================================
#  حالة التنقل
# ============================================================
if "view" not in st.session_state:
    st.session_state.view = "dashboard"
if "order_id" not in st.session_state:
    st.session_state.order_id = None


def go(view, order_id=None):
    st.session_state.view = view
    if order_id is not None:
        st.session_state.order_id = order_id


# ============================================================
#  الشريط الجانبي
# ============================================================
with st.sidebar:
    st.title("🧵 إدارة الملابس")
    st.caption("النسخة الويب")
    st.divider()
    if st.button("📊 لوحة المعلومات", use_container_width=True):
        go("dashboard"); rerun()
    if st.button("📦 الأوردرات", use_container_width=True):
        go("orders"); rerun()
    if st.button("📈 التقارير", use_container_width=True):
        go("reports"); rerun()
    st.divider()
    st.caption("الإصدار 1.0 — ويب")


# ============================================================
#  لوحة المعلومات
# ============================================================
def view_dashboard():
    st.header("📊 لوحة المعلومات")
    s = db.dashboard()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("عدد الأوردرات", s["orders"])
    c2.metric("عدد القطع", s["pieces"])
    c3.metric("إجمالي المبيعات", egp(s["sales"]))
    c4.metric("إجمالي التكاليف", egp(s["cost"]))
    c5.metric("صافي الأرباح", egp(s["profit"]))

    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("بانتظار الوزن", s["awaiting"])
    c7.metric("في الطريق", s["in_transit"])
    c8.metric("في المستودع", s["in_warehouse"])
    c9.metric("تم التسليم", s["delivered"])
    c10.metric("أرصدة مستحقة", egp(s["outstanding"]))

    st.divider()
    st.subheader("آخر الأوردرات")
    rows = db.all_orders()[:10]
    if rows:
        data = []
        for o in rows:
            summ = db.order_summary(o["id"])
            data.append({
                "رقم الأوردر": o["order_number"],
                "التاريخ": o["order_date"],
                "عدد القطع": summ["pieces"],
                "صافي الربح": egp(summ["profit"]),
            })
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد أوردرات بعد. أضف أوردر جديد من صفحة الأوردرات.")


# ============================================================
#  الأوردرات
# ============================================================
def view_orders():
    st.header("📦 إدارة الأوردرات")

    with st.expander("➕ إضافة أوردر جديد", expanded=False):
        with st.form("new_order", clear_on_submit=True):
            col1, col2 = st.columns(2)
            number = col1.text_input("رقم الأوردر")
            order_date = col2.date_input("تاريخ الأوردر", value=date.today())
            col3, col4, col5 = st.columns(3)
            buy_rate = col3.number_input("سعر اليوان وقت الشراء", min_value=0.0, step=0.1, format="%.2f")
            ship_rate = col4.number_input("سعر يوان الشحن (لاحقاً)", min_value=0.0, step=0.1, format="%.2f")
            ship_kg = col5.number_input("سعر كيلو الشحن باليوان (لاحقاً)", min_value=0.0, step=1.0, format="%.2f")
            notes = st.text_input("ملاحظات")
            if st.form_submit_button("حفظ الأوردر", type="primary"):
                if not number.strip():
                    st.error("اكتب رقم الأوردر.")
                else:
                    db.create_order(number.strip(), order_date.isoformat(), buy_rate, ship_rate, ship_kg, notes)
                    st.success("تم إضافة الأوردر.")
                    rerun()

    search = st.text_input("🔍 ابحث برقم الأوردر أو التاريخ", "")
    orders = db.all_orders()
    if search.strip():
        k = search.strip()
        orders = [o for o in orders if k in o["order_number"] or k in o["order_date"]]

    if not orders:
        st.info("لا توجد أوردرات.")
        return

    for o in orders:
        summ = db.order_summary(o["id"])
        with st.container(border=True):
            cols = st.columns([2, 2, 1, 2, 2])
            cols[0].markdown(f"**رقم:** {o['order_number']}")
            cols[1].markdown(f"**التاريخ:** {o['order_date']}")
            cols[2].markdown(f"**القطع:** {summ['pieces']}")
            cols[3].markdown(f"**الربح:** {egp(summ['profit'])}")
            if cols[4].button("📂 فتح التفاصيل", key=f"open_{o['id']}"):
                go("order_details", o["id"]); rerun()


# ============================================================
#  تفاصيل الأوردر
# ============================================================
def view_order_details():
    oid = st.session_state.order_id
    o = db.get_order(oid)
    if not o:
        st.error("الأوردر غير موجود.")
        if st.button("رجوع"):
            go("orders"); rerun()
        return

    cback, ctitle = st.columns([1, 4])
    if cback.button("← رجوع للأوردرات"):
        go("orders"); rerun()
    ctitle.header(f"تفاصيل الأوردر: {o['order_number']} • {o['order_date']}")

    # أسعار الأوردر
    with st.container(border=True):
        st.subheader("أسعار الأوردر")
        with st.form("rates"):
            c1, c2, c3 = st.columns(3)
            buy_rate = c1.number_input("سعر اليوان وقت الشراء", value=float(o["purchase_yuan_rate"]), step=0.1, format="%.2f")
            ship_rate = c2.number_input("سعر يوان الشحن", value=float(o["shipping_yuan_rate"]), step=0.1, format="%.2f")
            ship_kg = c3.number_input("سعر كيلو الشحن باليوان", value=float(o["shipping_price_per_kg_yuan"]), step=1.0, format="%.2f")
            st.caption("عند تعديل الأسعار يُعاد حساب كل القطع تلقائياً")
            if st.form_submit_button("💾 حفظ الأسعار وإعادة الحساب", type="primary"):
                db.update_order(oid, o["order_number"], o["order_date"], buy_rate, ship_rate, ship_kg, o["notes"])
                st.success("تم الحفظ وإعادة الحساب.")
                rerun()

    # إضافة قطعة
    with st.expander("➕ إضافة قطعة جديدة", expanded=False):
        _item_form(oid, item=None, form_key="add_item")

    # جدول القطع
    st.subheader("القطع داخل الأوردر")
    items = db.items_of(oid)
    if items:
        data = []
        for it in items:
            profit = "انتظار الوزن" if it["weight_grams"] <= 0 else egp(it["profit_egp"])
            data.append({
                "العميل": it["customer_name"],
                "المنتج": it["product_name"],
                "سعر البيع": egp(it["selling_price_egp"]),
                "شراء (يوان)": f'{it["purchase_price_yuan"]:g}',
                "الوزن (جم)": f'{it["weight_grams"]:g}',
                "تكلفة الشحن": egp(it["shipping_cost_egp"]),
                "إجمالي التكلفة": egp(it["total_cost_egp"]),
                "العربون": egp(it["deposit_paid"]),
                "الحالة": STATUS_AR.get(it["status"], it["status"]),
                "الربح": profit,
            })
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

        # تعديل / حذف قطعة
        st.markdown("##### تعديل أو حذف قطعة")
        opts = {f'{it["customer_name"]} — {it["product_name"]} (#{it["id"]})': it["id"] for it in items}
        chosen = st.selectbox("اختر قطعة", list(opts.keys()))
        chosen_id = opts[chosen]
        cedit, cdel = st.columns(2)
        with cedit.expander("✏️ تعديل القطعة المختارة"):
            _item_form(oid, item=db.get_item(chosen_id), form_key=f"edit_{chosen_id}")
        if cdel.button("🗑️ حذف القطعة المختارة"):
            db.delete_item(chosen_id)
            st.success("تم الحذف.")
            rerun()
    else:
        st.info("لا توجد قطع. أضف قطعة من الأعلى.")

    # الإجماليات
    s = db.order_summary(oid)
    st.divider()
    st.subheader("الإجماليات")
    t1, t2, t3, t4, t5 = st.columns(5)
    t1.metric("عدد القطع", s["pieces"])
    t2.metric("بانتظار الوزن", s["awaiting_weight"] or 0)
    t3.metric("إجمالي المبيعات", egp(s["sales"]))
    t4.metric("الودائع المجمّعة", egp(s["deposits"]))
    t5.metric("صافي الربح", egp(s["profit"]))


def _item_form(oid, item, form_key):
    """نموذج إضافة/تعديل قطعة مع معاينة حية."""
    order = db.get_order(oid)
    is_edit = item is not None

    with st.form(form_key, clear_on_submit=not is_edit):
        c1, c2 = st.columns(2)
        customer = c1.text_input("اسم العميل", value=item["customer_name"] if is_edit else "")
        product = c2.text_input("اسم المنتج", value=item["product_name"] if is_edit else "")
        c3, c4, c5 = st.columns(3)
        sell = c3.number_input("سعر البيع بالمصري", min_value=0.0, step=10.0,
                               value=float(item["selling_price_egp"]) if is_edit else 0.0, format="%.2f")
        buy_yuan = c4.number_input("سعر الشراء باليوان", min_value=0.0, step=1.0,
                                   value=float(item["purchase_price_yuan"]) if is_edit else 0.0, format="%.2f")
        weight = c5.number_input("الوزن بالجرام", min_value=0.0, step=10.0,
                                 value=float(item["weight_grams"]) if is_edit else 0.0, format="%.1f")
        c6, c7 = st.columns(2)
        deposit = c6.number_input("العربون المدفوع", min_value=0.0, step=10.0,
                                  value=float(item["deposit_paid"]) if is_edit else 0.0, format="%.2f")
        status_ar_list = [STATUS_AR[s] for s in ITEM_STATUSES]
        cur_status_ar = STATUS_AR.get(item["status"], status_ar_list[0]) if is_edit else status_ar_list[0]
        status_ar = c7.selectbox("الحالة", status_ar_list, index=status_ar_list.index(cur_status_ar))
        status_en = ITEM_STATUSES[status_ar_list.index(status_ar)]

        # معاينة الحساب
        c = calc_item(buy_yuan, weight, sell, order["purchase_yuan_rate"],
                      order["shipping_yuan_rate"], order["shipping_price_per_kg_yuan"])
        prof = "⏳ بانتظار إدخال الوزن" if c["profit_egp"] is None else egp(c["profit_egp"])
        st.caption(f"تكلفة الشراء: {egp(c['purchase_cost_egp'])} | تكلفة الشحن: {egp(c['shipping_cost_egp'])} | "
                   f"إجمالي التكلفة: {egp(c['total_cost_egp'])} | الربح: {prof}")

        label = "💾 حفظ التعديل" if is_edit else "➕ إضافة القطعة"
        if st.form_submit_button(label, type="primary"):
            if not customer.strip() or not product.strip():
                st.error("اكتب اسم العميل واسم المنتج.")
            else:
                if is_edit:
                    db.update_item(item["id"], customer.strip(), product.strip(), sell, buy_yuan, weight, deposit, status_en)
                    st.success("تم تعديل القطعة.")
                else:
                    db.create_item(oid, customer.strip(), product.strip(), sell, buy_yuan, weight, deposit, status_en)
                    st.success("تمت إضافة القطعة.")
                rerun()


# ============================================================
#  التقارير + تصدير Excel
# ============================================================
def view_reports():
    st.header("📈 التقارير")

    tab1, tab2, tab3, tab4 = st.tabs(["أرباح الأوردرات", "أرباح العملاء", "أرباح شهرية", "أرباح سنوية"])

    with tab1:
        rows = db.report_by_order()
        df = pd.DataFrame([{
            "رقم الأوردر": r["order_number"], "التاريخ": r["order_date"], "عدد القطع": r["pieces"],
            "إجمالي الشراء (يوان)": round(r["yuan_total"], 2),
            "المبيعات": round(r["sales"], 2), "التكاليف": round(r["cost"], 2), "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab2:
        rows = db.report_by_customer()
        df = pd.DataFrame([{
            "اسم العميل": r["customer_name"], "عدد القطع": r["pieces"], "المبيعات": round(r["sales"], 2),
            "الودائع": round(r["deposits"], 2), "الرصيد المتبقي": round(r["balance"], 2),
            "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab3:
        rows = db.report_monthly()
        df = pd.DataFrame([{
            "الشهر": r["period"], "عدد القطع": r["pieces"], "المبيعات": round(r["sales"], 2),
            "التكاليف": round(r["cost"], 2), "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab4:
        rows = db.report_yearly()
        df = pd.DataFrame([{
            "السنة": r["period"], "عدد القطع": r["pieces"], "المبيعات": round(r["sales"], 2),
            "التكاليف": round(r["cost"], 2), "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    st.download_button("📥 تصدير كل التقارير Excel", data=_build_excel(),
                       file_name="تقارير.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       type="primary")


def _build_excel():
    buf = io.BytesIO()
    items = db.all_items_detailed()
    items_df = pd.DataFrame([{
        "رقم الأوردر": r["order_number"], "التاريخ": r["order_date"], "العميل": r["customer_name"],
        "المنتج": r["product_name"], "سعر البيع": r["selling_price_egp"], "شراء (يوان)": r["purchase_price_yuan"],
        "الوزن (جم)": r["weight_grams"], "العربون": r["deposit_paid"], "الحالة": STATUS_AR.get(r["status"], r["status"]),
        "تكلفة الشراء": r["purchase_cost_egp"], "تكلفة الشحن": r["shipping_cost_egp"],
        "إجمالي التكلفة": r["total_cost_egp"], "الربح": r["profit_egp"],
    } for r in items])

    def df_of(rows, cols):
        return pd.DataFrame([{c[1]: r[c[0]] for c in cols} for r in rows])

    by_order = df_of(db.report_by_order(), [("order_number","رقم الأوردر"),("order_date","التاريخ"),
                     ("pieces","عدد القطع"),("yuan_total","إجمالي الشراء (يوان)"),
                     ("sales","المبيعات"),("cost","التكاليف"),("profit","الربح")])
    by_cust = df_of(db.report_by_customer(), [("customer_name","العميل"),("pieces","عدد القطع"),
                    ("sales","المبيعات"),("deposits","الودائع"),("balance","الرصيد"),("profit","الربح")])
    monthly = df_of(db.report_monthly(), [("period","الشهر"),("pieces","عدد القطع"),
                    ("sales","المبيعات"),("cost","التكاليف"),("profit","الربح")])
    yearly = df_of(db.report_yearly(), [("period","السنة"),("pieces","عدد القطع"),
                   ("sales","المبيعات"),("cost","التكاليف"),("profit","الربح")])

    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        items_df.to_excel(w, sheet_name="تفاصيل القطع", index=False)
        by_order.to_excel(w, sheet_name="أرباح الأوردرات", index=False)
        by_cust.to_excel(w, sheet_name="أرباح العملاء", index=False)
        monthly.to_excel(w, sheet_name="أرباح شهرية", index=False)
        yearly.to_excel(w, sheet_name="أرباح سنوية", index=False)
    buf.seek(0)
    return buf


# ============================================================
#  التوجيه
# ============================================================
view = st.session_state.view
if view == "dashboard":
    view_dashboard()
elif view == "orders":
    view_orders()
elif view == "order_details":
    view_order_details()
elif view == "reports":
    view_reports()
