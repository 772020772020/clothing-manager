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

from db import Database, ITEM_STATUSES, STATUS_AR, USA_STATUSES, USA_STATUS_AR
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

# إنشاء جداول أمريكا تلقائياً لو مش موجودة (مرة واحدة)
@st.cache_resource
def _ensure_usa_tables():
    try:
        db.usa_init()
    except Exception as e:
        st.warning(f"تنبيه: لم يتم إنشاء جداول أمريكا تلقائياً ({e}).")
    return True

_ensure_usa_tables()


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

USA_VIEWS = {"usa_dashboard", "usa_orders", "usa_order_details", "usa_reports"}
in_usa = st.session_state.get("view", "dashboard") in USA_VIEWS

# سطر تبديل النظام (الصين / أمريكا) + تحديث
s1, s2, s3 = st.columns(3)
if s1.button(("🟢 " if not in_usa else "") + "🇨🇳 الصين", use_container_width=True):
    go("dashboard"); rerun()
if s2.button(("🟢 " if in_usa else "") + "🇺🇸 أمريكا", use_container_width=True):
    go("usa_dashboard"); rerun()
if s3.button("🔄 تحديث", use_container_width=True):
    st.cache_data.clear(); rerun()

# سطر أقسام النظام الحالي
if in_usa:
    n1, n2, n3 = st.columns(3)
    if n1.button("📊 لوحة أمريكا", use_container_width=True):
        go("usa_dashboard"); rerun()
    if n2.button("📦 أوردرات أمريكا", use_container_width=True):
        go("usa_orders"); rerun()
    if n3.button("📈 تقارير أمريكا", use_container_width=True):
        go("usa_reports"); rerun()
else:
    n1, n2, n3 = st.columns(3)
    if n1.button("📊 لوحة المعلومات", use_container_width=True):
        go("dashboard"); rerun()
    if n2.button("📦 الأوردرات", use_container_width=True):
        go("orders"); rerun()
    if n3.button("📈 التقارير", use_container_width=True):
        go("reports"); rerun()
st.divider()


def _render_customer_search(key_prefix):
    """خانة بحث باسم العميل + ملخصه وكل قطعه. تُستخدم في أكثر من صفحة."""
    search = st.text_input("اكتب اسم العميل (أو جزء منه)", key=f"{key_prefix}_search")
    custs = db.customers_list()
    if search.strip():
        matches = [c for c in custs if search.strip().lower() in c.lower()]
    else:
        matches = custs

    if not custs:
        st.info("لا يوجد عملاء بعد.")
        return
    if not matches:
        st.warning("لا يوجد عميل بهذا الاسم.")
        return

    chosen_cust = st.selectbox("اختر العميل", matches, key=f"{key_prefix}_cust")
    if not chosen_cust:
        return
    citems = db.items_of_customer(chosen_cust)
    # نستبعد القطع المرتجعة من كل الحسابات
    active = [it for it in citems if it["status"] not in ("Out of Stock", "Cancelled")]
    tot_sales = sum(it["selling_price_egp"] or 0 for it in active)
    tot_dep = sum(it["deposit_paid"] or 0 for it in active)
    tot_bal = tot_sales - tot_dep
    tot_yuan = sum(it["purchase_price_yuan"] or 0 for it in active)
    tot_profit = sum((it["profit_egp"] or 0) for it in active if it["weight_grams"] > 0)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("عدد القطع", len(active))
    m2.metric("إجمالي البيع", egp(tot_sales))
    m3.metric("المدفوع (عربون)", egp(tot_dep))
    m4.metric("المتبقي عليه", egp(tot_bal))
    m5.metric("صافي الربح", egp(tot_profit))
    st.caption(f"إجمالي الشراء باليوان لكل قطعه: {tot_yuan:g} يوان")

    cdata = []
    for it in citems:
        profit = "انتظار الوزن" if it["weight_grams"] <= 0 else egp(it["profit_egp"])
        cdata.append({
            "رقم الأوردر": it["order_number"],
            "المنتج": it["product_name"],
            "سعر البيع": egp(it["selling_price_egp"]),
            "شراء (يوان)": f'{it["purchase_price_yuan"]:g}',
            "الوزن (جم)": f'{it["weight_grams"]:g}',
            "العربون": egp(it["deposit_paid"]),
            "المتبقي": egp((it["selling_price_egp"] or 0) - (it["deposit_paid"] or 0)),
            "الحالة": STATUS_AR.get(it["status"], it["status"]),
            "الربح": profit,
        })
    st.dataframe(_style_profit(pd.DataFrame(cdata)), use_container_width=True, hide_index=True)


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
                "شراء (يوان)": f'{it["purchase_price_yuan"]:g}',
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

    st.divider()
    st.subheader("👤 بحث عن عميل")
    _render_customer_search("dash")

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

    # ملاحظات الأوردر
    with st.container(border=True):
        st.subheader("📝 ملاحظات الأوردر")
        new_notes = st.text_area("الملاحظة", value=o["notes"] or "", key=f"notes_{oid}",
                                 placeholder="اكتب أي ملاحظة على الأوردر هنا...")
        if st.button("💾 حفظ الملاحظة", key=f"save_notes_{oid}"):
            db.update_order(oid, o["order_number"], o["order_date"],
                            o["purchase_yuan_rate"], o["shipping_yuan_rate"],
                            o["shipping_price_per_kg_yuan"], new_notes)
            st.success("تم حفظ الملاحظة.")
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
            "اسم العميل": r["customer_name"], "عدد القطع": r["pieces"],
            "إجمالي الشراء (يوان)": round(r["yuan_total"], 2),
            "المبيعات": round(r["sales"], 2),
            "الودائع": round(r["deposits"], 2), "الرصيد المتبقي": round(r["balance"], 2),
            "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)

        # 🔍 بحث باسم العميل وعرض كل بياناته
        st.divider()
        st.markdown("##### 🔍 بحث عن عميل بالاسم")
        _render_customer_search("rep")

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
                    "شراء (يوان)": f'{it["purchase_price_yuan"]:g}',
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
                    ("yuan_total","إجمالي الشراء (يوان)"),
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
#  نظام أمريكا (واجهات منفصلة)
# ============================================================
def _usa_item_form(oid, item, form_key):
    """نموذج إضافة/تعديل قطعة أمريكا (حساب مبسّط: ربح = بيع − تكلفة)."""
    is_edit = item is not None
    k = form_key
    c1, c2 = st.columns(2)
    customer = c1.text_input("اسم العميل", value=item["customer_name"] if is_edit else "", key=f"{k}_cust")
    product = c2.text_input("اسم المنتج", value=item["product_name"] if is_edit else "", key=f"{k}_prod")
    c3, c4, c5 = st.columns(3)
    with c3:
        cost = _num("تكلفة الأوردر (ج.م)", item["cost_egp"] if is_edit else 0, key=f"{k}_cost")
    with c4:
        sell = _num("سعر البيع (ج.م)", item["selling_price_egp"] if is_edit else 0, key=f"{k}_sell")
    with c5:
        deposit = _num("العربون (ج.م)", item["deposit_paid"] if is_edit else 0, key=f"{k}_dep")
    cur_status = item["status"] if is_edit else "In Transit"
    status = st.selectbox("الحالة", USA_STATUSES,
                          index=USA_STATUSES.index(cur_status) if cur_status in USA_STATUSES else 0,
                          format_func=lambda s: USA_STATUS_AR.get(s, s), key=f"{k}_status")
    # معاينة الربح
    profit = (sell or 0) - (cost or 0)
    st.caption(f"💰 الربح المتوقع: {egp(profit)}  |  المتبقي على العميل: {egp((sell or 0) - (deposit or 0))}")

    if st.button("💾 حفظ", type="primary", key=f"{k}_save"):
        if not customer.strip() and not product.strip():
            st.error("اكتب اسم العميل أو المنتج على الأقل.")
        else:
            if is_edit:
                db.usa_update_item(item["id"], customer, product, cost, sell, deposit, status)
                st.success("تم تعديل القطعة.")
            else:
                db.usa_add_item(oid, customer, product, cost, sell, deposit, status)
                st.success("تم إضافة القطعة.")
            rerun()


def view_usa_dashboard():
    st.header("📊 لوحة معلومات أمريكا")
    d = db.usa_dashboard()
    a, b, c, e = st.columns(4)
    a.metric("عدد الأوردرات", d["orders"])
    b.metric("عدد القطع", d["pieces"])
    c.metric("إجمالي المبيعات", egp(d["sales"]))
    e.metric("صافي الربح", egp(d["profit"]))
    a2, b2 = st.columns(2)
    a2.metric("إجمالي التكاليف", egp(d["cost"]))
    b2.metric("المتبقي على العملاء", egp(d["outstanding"]))

    st.divider()
    st.subheader("👤 بحث عن عميل (أمريكا)")
    _render_usa_customer_search("usa_dash")

    st.divider()
    st.subheader("آخر أوردرات أمريكا")
    orders = db.usa_all_orders()
    if orders:
        data = []
        for o in orders[:10]:
            summ = db.usa_order_summary(o["id"])
            data.append({
                "رقم الأوردر": o["order_number"],
                "المورد": o["supplier_name"],
                "التاريخ": o["order_date"],
                "عدد القطع": summ["pieces"],
                "صافي الربح": egp(summ["profit"]),
            })
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد أوردرات أمريكا بعد. أضف من صفحة الأوردرات.")


def _render_usa_customer_search(key_prefix):
    search = st.text_input("اكتب اسم العميل (أو جزء منه)", key=f"{key_prefix}_search")
    custs = db.usa_customers_list()
    matches = [c for c in custs if search.strip().lower() in c.lower()] if search.strip() else custs
    if not custs:
        st.info("لا يوجد عملاء بعد.")
        return
    if not matches:
        st.warning("لا يوجد عميل بهذا الاسم.")
        return
    chosen = st.selectbox("اختر العميل", matches, key=f"{key_prefix}_cust")
    if not chosen:
        return
    citems = db.usa_items_of_customer(chosen)
    tot_sales = sum(it["selling_price_egp"] or 0 for it in citems)
    tot_cost = sum(it["cost_egp"] or 0 for it in citems)
    tot_dep = sum(it["deposit_paid"] or 0 for it in citems)
    tot_profit = sum(it["profit_egp"] or 0 for it in citems)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("عدد القطع", len(citems))
    m2.metric("إجمالي البيع", egp(tot_sales))
    m3.metric("المدفوع (عربون)", egp(tot_dep))
    m4.metric("المتبقي عليه", egp(tot_sales - tot_dep))
    m5.metric("صافي الربح", egp(tot_profit))
    cdata = []
    for it in citems:
        cdata.append({
            "رقم الأوردر": it["order_number"],
            "المورد": it["supplier_name"],
            "المنتج": it["product_name"],
            "التكلفة": egp(it["cost_egp"]),
            "سعر البيع": egp(it["selling_price_egp"]),
            "العربون": egp(it["deposit_paid"]),
            "المتبقي": egp((it["selling_price_egp"] or 0) - (it["deposit_paid"] or 0)),
            "الحالة": USA_STATUS_AR.get(it["status"], it["status"]),
            "الربح": egp(it["profit_egp"]),
        })
    st.dataframe(_style_profit(pd.DataFrame(cdata)), use_container_width=True, hide_index=True)


def view_usa_orders():
    st.header("📦 أوردرات أمريكا")
    with st.expander("➕ إضافة أوردر جديد", expanded=False):
        col1, col2 = st.columns(2)
        number = col1.text_input("رقم الأوردر", key="usa_no_num")
        order_date = col2.date_input("تاريخ الأوردر", value=date.today(), key="usa_no_date")
        supplier = st.text_input("اسم المورد", key="usa_no_supplier")
        notes = st.text_input("ملاحظات", key="usa_no_notes")
        if st.button("حفظ الأوردر", type="primary", key="usa_no_save"):
            if not number.strip():
                st.error("اكتب رقم الأوردر.")
            else:
                db.usa_create_order(number.strip(), order_date.isoformat(), supplier.strip(), notes)
                st.success("تم إضافة الأوردر.")
                rerun()

    search = st.text_input("🔍 ابحث برقم الأوردر أو المورد", "", key="usa_search")
    orders = db.usa_all_orders()
    if search.strip():
        k = search.strip().lower()
        orders = [o for o in orders if k in o["order_number"].lower()
                  or k in (o["supplier_name"] or "").lower() or k in o["order_date"]]
    if not orders:
        st.info("لا توجد أوردرات.")
        return
    for o in orders:
        summ = db.usa_order_summary(o["id"])
        with st.container(border=True):
            cols = st.columns([2, 2, 1, 2, 2])
            cols[0].markdown(f"**رقم:** {o['order_number']}")
            cols[1].markdown(f"**المورد:** {o['supplier_name'] or '—'}")
            cols[2].markdown(f"**القطع:** {summ['pieces']}")
            cols[3].markdown(f"**الربح:** {egp(summ['profit'])}")
            if cols[4].button("📂 فتح التفاصيل", key=f"usa_open_{o['id']}"):
                go("usa_order_details", o["id"]); rerun()


def view_usa_order_details():
    oid = st.session_state.order_id
    o = db.usa_get_order(oid)
    if not o:
        st.error("الأوردر غير موجود.")
        if st.button("رجوع"):
            go("usa_orders"); rerun()
        return
    cback, ctitle = st.columns([1, 4])
    if cback.button("← رجوع للأوردرات"):
        go("usa_orders"); rerun()
    ctitle.header(f"أوردر أمريكا: {o['order_number']} • {o['order_date']}")

    # معلومات الأوردر
    with st.container(border=True):
        st.subheader("معلومات الأوردر")
        c1, c2 = st.columns(2)
        new_num = c1.text_input("رقم الأوردر", value=o["order_number"], key=f"usa_num_{oid}")
        new_supplier = c2.text_input("اسم المورد", value=o["supplier_name"] or "", key=f"usa_sup_{oid}")
        new_notes = st.text_area("📝 ملاحظات", value=o["notes"] or "", key=f"usa_notes_{oid}")
        if st.button("💾 حفظ معلومات الأوردر", type="primary", key=f"usa_savord_{oid}"):
            db.usa_update_order(oid, new_num.strip() or o["order_number"], o["order_date"],
                                new_supplier.strip(), new_notes)
            st.success("تم الحفظ.")
            rerun()

    with st.expander("➕ إضافة قطعة جديدة", expanded=False):
        _usa_item_form(oid, item=None, form_key="usa_add_item")

    st.subheader("القطع داخل الأوردر")
    items = db.usa_items_of(oid)
    if items:
        data = []
        for it in items:
            data.append({
                "العميل": it["customer_name"],
                "المنتج": it["product_name"],
                "التكلفة": egp(it["cost_egp"]),
                "سعر البيع": egp(it["selling_price_egp"]),
                "العربون": egp(it["deposit_paid"]),
                "المتبقي": egp((it["selling_price_egp"] or 0) - (it["deposit_paid"] or 0)),
                "الحالة": USA_STATUS_AR.get(it["status"], it["status"]),
                "الربح": egp(it["profit_egp"]),
            })
        st.dataframe(_style_profit(pd.DataFrame(data)), use_container_width=True, hide_index=True)

        st.markdown("##### تعديل أو حذف قطعة")
        opts = {f'{it["customer_name"]} — {it["product_name"]} (#{it["id"]})': it["id"] for it in items}
        chosen = st.selectbox("اختر قطعة", list(opts.keys()), key=f"usa_pick_{oid}")
        chosen_id = opts[chosen]
        cedit, cdel = st.columns(2)
        chosen_item = next(it for it in items if it["id"] == chosen_id)
        with cedit.expander("✏️ تعديل القطعة المختارة"):
            _usa_item_form(oid, item=chosen_item, form_key=f"usa_edit_{chosen_id}")
        if cdel.button("🗑️ حذف القطعة المختارة", key=f"usa_del_{oid}"):
            db.usa_delete_item(chosen_id)
            st.success("تم الحذف.")
            rerun()
    else:
        st.info("لا توجد قطع. أضف قطعة من الأعلى.")

    s = db.usa_order_summary(oid)
    st.divider()
    st.subheader("الإجماليات")
    t1, t2, t3, t4, t5 = st.columns(5)
    t1.metric("عدد القطع", s["pieces"])
    t2.metric("إجمالي التكلفة", egp(s["cost"]))
    t3.metric("إجمالي المبيعات", egp(s["sales"]))
    t4.metric("الودائع المجمّعة", egp(s["deposits"]))
    t5.metric("صافي الربح", egp(s["profit"]))


def view_usa_reports():
    st.header("📈 تقارير أمريكا")
    tab1, tab2, tab3, tab4 = st.tabs(["أرباح الأوردرات", "أرباح العملاء", "أرباح شهرية", "أرباح سنوية"])
    with tab1:
        rows = db.usa_report_by_order()
        df = pd.DataFrame([{
            "رقم الأوردر": r["order_number"], "المورد": r["supplier_name"],
            "التاريخ": r["order_date"], "عدد القطع": r["pieces"],
            "التكلفة": round(r["cost"], 2), "المبيعات": round(r["sales"], 2),
            "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab2:
        rows = db.usa_report_by_customer()
        df = pd.DataFrame([{
            "اسم العميل": r["customer_name"], "عدد القطع": r["pieces"],
            "التكلفة": round(r["cost"], 2), "المبيعات": round(r["sales"], 2),
            "الودائع": round(r["deposits"], 2), "الرصيد المتبقي": round(r["balance"], 2),
            "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.divider()
        st.markdown("##### 🔍 بحث عن عميل بالاسم")
        _render_usa_customer_search("usa_rep")
    with tab3:
        rows = db.usa_report_monthly()
        df = pd.DataFrame([{
            "الشهر": r["period"], "عدد القطع": r["pieces"],
            "التكلفة": round(r["cost"], 2), "المبيعات": round(r["sales"], 2),
            "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tab4:
        rows = db.usa_report_yearly()
        df = pd.DataFrame([{
            "السنة": r["period"], "عدد القطع": r["pieces"],
            "التكلفة": round(r["cost"], 2), "المبيعات": round(r["sales"], 2),
            "الربح": round(r["profit"], 2),
        } for r in rows])
        st.dataframe(df, use_container_width=True, hide_index=True)


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
elif view == "usa_dashboard":
    view_usa_dashboard()
elif view == "usa_orders":
    view_usa_orders()
elif view == "usa_order_details":
    view_usa_order_details()
elif view == "usa_reports":
    view_usa_reports()
