# -*- coding: utf-8 -*-
"""
app.py
نسخة الويب من برنامج إدارة تجارة الملابس المستوردة (Streamlit).
التشغيل:  streamlit run app.py
"""

import io
from datetime import date, datetime
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
    h1, h2, h3, h4, h5, h6, p, label, div, span { text-align: right; }
    .stDataFrame { direction: ltr; }
    [data-testid="stMetricValue"] { direction: ltr; text-align: center; }
    [data-testid="stMetricLabel"] { justify-content: center; }
    .stButton button { width: 100%; }
    /* إخفاء القايمة الجانبية وزر فتحها نهائياً (التنقل بقى فوق) */
    section[data-testid="stSidebar"] { display: none !important; }
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    /* تحسين العرض على الموبايل */
    @media (max-width: 640px) {
        [data-testid="stMetricValue"] { font-size: 1.4rem; }
        h1 { font-size: 1.5rem; }
        h2 { font-size: 1.3rem; }
        h3 { font-size: 1.1rem; }
        .block-container { padding-top: 2rem; padding-left: 0.8rem; padding-right: 0.8rem; }
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


def _is_loss(text):
    """يتحقق لو القيمة في عمود الربح خسارة (سالبة)."""
    s = str(text)
    return s.strip().startswith("-") or "-" in s.split("ج.م")[0]


def _style_profit(df, col="الربح"):
    """تلوين القيم الخاسرة بالأحمر في عمود الربح (متوافق مع كل إصدارات pandas)."""
    if col not in df.columns or df.empty:
        return df

    def color(val):
        return "color: #d62728; font-weight: 700;" if _is_loss(val) else ""

    try:
        styler = df.style
        # pandas الأحدث يستخدم map بدل applymap
        if hasattr(styler, "map"):
            return styler.map(color, subset=[col])
        return styler.applymap(color, subset=[col])
    except Exception:
        return df


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
# ============================================================
#  شريط التنقل العلوي (بدل القايمة الجانبية)
# ============================================================
st.markdown("#### 🧵 إدارة الملابس المستوردة")
nav1, nav2, nav3 = st.columns(3)
if nav1.button("📊 لوحة المعلومات", use_container_width=True):
    go("dashboard"); rerun()
if nav2.button("📦 الأوردرات", use_container_width=True):
    go("orders"); rerun()
if nav3.button("📈 التقارير", use_container_width=True):
    go("reports"); rerun()
st.divider()


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
    # استعراض القطع حسب الحالة + الدخول على أي قطعة وتعديلها
    st.subheader("🔍 استعراض القطع حسب الحالة")
    status_ar_list = [STATUS_AR[s] for s in ITEM_STATUSES]
    # نعرض عدّاد جنب كل حالة
    counts = db.status_counts()
    labels = []
    for en in ITEM_STATUSES:
        ar = STATUS_AR[en]
        labels.append(f"{ar} ({counts.get(en, 0)})")
    picked = st.selectbox("اختر الحالة لعرض قطعها", labels, key="dash_status_filter")
    picked_en = ITEM_STATUSES[labels.index(picked)]

    status_items = db.items_by_status(picked_en)
    if status_items:
        # جدول سريع للقطع
        tbl = []
        for it in status_items:
            profit = "انتظار الوزن" if it["weight_grams"] <= 0 else egp(it["profit_egp"])
            tbl.append({
                "أوردر": it["order_number"],
                "العميل": it["customer_name"],
                "المنتج": it["product_name"],
                "الوزن (جم)": f'{it["weight_grams"]:g}',
                "سعر البيع": egp(it["selling_price_egp"]),
                "الربح": profit,
            })
        st.dataframe(_style_profit(pd.DataFrame(tbl)), use_container_width=True, hide_index=True)
        st.caption(f"عدد القطع في هذه الحالة: {len(status_items)}")

        # الدخول على قطعة معيّنة وتعديلها بالكامل
        st.markdown("##### الدخول على قطعة وتعديلها")
        opts = {
            f'أوردر {it["order_number"]} — {it["customer_name"]} — {it["product_name"]} (#{it["id"]})': it["id"]
            for it in status_items
        }
        chosen_label = st.selectbox("اختر القطعة", list(opts.keys()), key="dash_pick_item")
        chosen_id = opts[chosen_label]
        chosen_item = db.get_item(chosen_id)
        oid_of_item = chosen_item["order_id"]
        with st.expander("✏️ تعديل القطعة المختارة (كل التفاصيل)", expanded=True):
            _item_form(oid_of_item, item=chosen_item, form_key=f"dash_edit_{chosen_id}")
    else:
        st.info("لا توجد قطع في هذه الحالة.")

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
        col1, col2 = st.columns(2)
        number = col1.text_input("رقم الأوردر", key="no_num")
        order_date = col2.date_input("تاريخ الأوردر", value=date.today(), key="no_date")
        col3, col4, col5 = st.columns(3)
        with col3:
            buy_rate = _num("سعر اليوان وقت الشراء", 0, key="no_buy")
        with col4:
            ship_rate = _num("سعر يوان الشحن (لاحقاً)", 0, key="no_shiprate")
        with col5:
            ship_kg = _num("سعر كيلو الشحن باليوان (لاحقاً)", 0, key="no_shipkg")
        notes = st.text_input("ملاحظات", key="no_notes")
        if st.button("حفظ الأوردر", type="primary", key="no_save"):
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
        c1, c2, c3 = st.columns(3)
        with c1:
            buy_rate = _num("سعر اليوان وقت الشراء", o["purchase_yuan_rate"], key=f"rate_buy_{oid}")
        with c2:
            ship_rate = _num("سعر يوان الشحن", o["shipping_yuan_rate"], key=f"rate_ship_{oid}")
        with c3:
            ship_kg = _num("سعر كيلو الشحن باليوان", o["shipping_price_per_kg_yuan"], key=f"rate_kg_{oid}")
        st.caption("عند تعديل الأسعار يُعاد حساب كل القطع تلقائياً")
        if st.button("💾 حفظ الأسعار وإعادة الحساب", type="primary", key=f"save_rates_{oid}"):
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
        df = pd.DataFrame(data)
        st.dataframe(_style_profit(df), use_container_width=True, hide_index=True)

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


def _num(label, value, key):
    """حقل رقمي يظهر فاضي بدل 0.00 (نص يتحوّل لرقم)."""
    txt = st.text_input(label, value=("" if (value in (None, 0, 0.0)) else _fmt_plain(value)), key=key)
    txt = (txt or "").strip().replace(",", "")
    if txt == "":
        return 0.0
    try:
        return float(txt)
    except ValueError:
        return 0.0


def _fmt_plain(v):
    f = float(v)
    return str(int(f)) if f == int(f) else str(f)


def _item_form(oid, item, form_key):
    """نموذج إضافة/تعديل قطعة مع معاينة حية."""
    order = db.get_order(oid)
    is_edit = item is not None
    k = form_key  # بادئة فريدة للحقول

    c1, c2 = st.columns(2)
    customer = c1.text_input("اسم العميل", value=item["customer_name"] if is_edit else "", key=f"{k}_cust")
    product = c2.text_input("اسم المنتج", value=item["product_name"] if is_edit else "", key=f"{k}_prod")
    c3, c4, c5 = st.columns(3)
    with c3:
        sell = _num("سعر البيع بالمصري", item["selling_price_egp"] if is_edit else 0, key=f"{k}_sell")
    with c4:
        buy_yuan = _num("سعر الشراء باليوان", item["purchase_price_yuan"] if is_edit else 0, key=f"{k}_buy")
    with c5:
        weight = _num("الوزن بالجرام", item["weight_grams"] if is_edit else 0, key=f"{k}_wt")
    c6, c7 = st.columns(2)
    with c6:
        deposit = _num("العربون المدفوع", item["deposit_paid"] if is_edit else 0, key=f"{k}_dep")
    status_ar_list = [STATUS_AR[s] for s in ITEM_STATUSES]
    cur_status_ar = STATUS_AR.get(item["status"], status_ar_list[0]) if is_edit else status_ar_list[0]
    status_ar = c7.selectbox("الحالة", status_ar_list, index=status_ar_list.index(cur_status_ar), key=f"{k}_st")
    status_en = ITEM_STATUSES[status_ar_list.index(status_ar)]

    # تاريخ تسجيل الوزن (يظهر فقط لو فيه وزن) — يمكن تعديله يدوياً
    weight_date = None
    if weight > 0:
        existing = None
        if is_edit and item.get("weight_date"):
            try:
                existing = datetime.strptime(item["weight_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                existing = date.today()
        wd = st.date_input("تاريخ وصول/تسجيل الوزن", value=existing or date.today(), key=f"{k}_wd")
        weight_date = wd.isoformat()

    # معاينة الحساب
    c = calc_item(buy_yuan, weight, sell, order["purchase_yuan_rate"],
                  order["shipping_yuan_rate"], order["shipping_price_per_kg_yuan"])
    prof = "⏳ بانتظار إدخال الوزن" if c["profit_egp"] is None else egp(c["profit_egp"])
    st.caption(f"تكلفة الشراء: {egp(c['purchase_cost_egp'])} | تكلفة الشحن: {egp(c['shipping_cost_egp'])} | "
               f"إجمالي التكلفة: {egp(c['total_cost_egp'])} | الربح: {prof}")

    label = "💾 حفظ التعديل" if is_edit else "➕ إضافة القطعة"
    if st.button(label, type="primary", key=f"{k}_save"):
        if not customer.strip() or not product.strip():
            st.error("اكتب اسم العميل واسم المنتج.")
        else:
            if is_edit:
                db.update_item(item["id"], customer.strip(), product.strip(), sell, buy_yuan,
                               weight, deposit, status_en, weight_date)
                st.success("تم تعديل القطعة.")
            else:
                db.create_item(oid, customer.strip(), product.strip(), sell, buy_yuan,
                               weight, deposit, status_en, weight_date)
                st.success("تمت إضافة القطعة.")
            rerun()



# ============================================================
#  التقارير + تصدير Excel
# ============================================================
def view_reports():
    st.header("📈 التقارير")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["أرباح الأوردرات", "أرباح العملاء", "الواصل في يوم", "أرباح شهرية", "أرباح سنوية"])

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

        # الدخول على عميل لعرض قطعه
        st.markdown("##### عرض تفاصيل عميل")
        custs = db.customers_list()
        if custs:
            chosen_cust = st.selectbox("اختر العميل", custs, key="rep_cust")
            if chosen_cust:
                citems = db.items_of_customer(chosen_cust)
                cdata = []
                for it in citems:
                    profit = "انتظار الوزن" if it["weight_grams"] <= 0 else egp(it["profit_egp"])
                    cdata.append({
                        "رقم الأوردر": it["order_number"],
                        "المنتج": it["product_name"],
                        "سعر البيع": egp(it["selling_price_egp"]),
                        "الوزن (جم)": f'{it["weight_grams"]:g}',
                        "العربون": egp(it["deposit_paid"]),
                        "الحالة": STATUS_AR.get(it["status"], it["status"]),
                        "الربح": profit,
                    })
                st.dataframe(_style_profit(pd.DataFrame(cdata)), use_container_width=True, hide_index=True)
        else:
            st.info("لا يوجد عملاء بعد.")

    with tab3:
        st.markdown("##### ربح القطع التي وصلت (سُجّل وزنها) في يوم معين")
        chosen_day = st.date_input("اختر اليوم", value=date.today(), key="arr_day")
        day_str = chosen_day.isoformat()
        arr = db.items_by_weight_date(day_str)
        if arr:
            adata = []
            total_profit = 0.0
            total_sales = 0.0
            for it in arr:
                total_profit += it["profit_egp"] or 0
                total_sales += it["selling_price_egp"] or 0
                adata.append({
                    "رقم الأوردر": it["order_number"],
                    "العميل": it["customer_name"],
                    "المنتج": it["product_name"],
                    "الوزن (جم)": f'{it["weight_grams"]:g}',
                    "سعر البيع": egp(it["selling_price_egp"]),
                    "إجمالي التكلفة": egp(it["total_cost_egp"]),
                    "الربح": egp(it["profit_egp"]),
                })
            m1, m2, m3 = st.columns(3)
            m1.metric("عدد القطع الواصلة", len(arr))
            m2.metric("إجمالي مبيعاتها", egp(total_sales))
            m3.metric("إجمالي ربحها", egp(total_profit))
            st.dataframe(_style_profit(pd.DataFrame(adata)), use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد قطع سُجّل وزنها في هذا اليوم.")

    with tab4:
        rows = db.report_monthly()
        df = pd.DataFrame([{
            "الشهر": r["period"], "عدد القطع": r["pieces"], "المبيعات": round(r["sales"], 2),
            "التكاليف": round(r["cost"], 2), "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab5:
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
