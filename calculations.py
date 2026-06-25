# -*- coding: utf-8 -*-
"""
calculations.py
كل معادلات الحساب في مكان واحد.

المعادلات:
    تكلفة الشراء   = سعر الشراء باليوان × سعر اليوان وقت الشراء
    تكلفة الشحن    = (الوزن_بالجرام / 1000) × سعر كيلو الشحن باليوان × سعر يوان الشحن
    إجمالي التكلفة = تكلفة الشراء + تكلفة الشحن
    الربح          = سعر البيع - إجمالي التكلفة

إذا كان الوزن = 0/null، فإن الربح يكون NULL ("Awaiting Weight")
"""


def calc_item(purchase_price_yuan, weight_grams, selling_price_egp,
              purchase_yuan_rate, shipping_yuan_rate, shipping_price_per_kg_yuan):
    """
    تحسب القيم المشتقة لقطعة واحدة وترجعها كـ dict.
    كل المدخلات أرقام (float).
    
    إذا كان weight_grams = 0 أو null، يُرجع None للربح ("Awaiting Weight").
    """
    purchase_price_yuan = float(purchase_price_yuan or 0)
    weight_grams = float(weight_grams or 0)
    selling_price_egp = float(selling_price_egp or 0)
    purchase_yuan_rate = float(purchase_yuan_rate or 0)
    shipping_yuan_rate = float(shipping_yuan_rate or 0)
    shipping_price_per_kg_yuan = float(shipping_price_per_kg_yuan or 0)

    # تكلفة الشراء
    purchase_cost_egp = purchase_price_yuan * purchase_yuan_rate
    
    # إذا لم يدخل الوزن بعد
    if weight_grams <= 0:
        return {
            "purchase_cost_egp": round(purchase_cost_egp, 2),
            "shipping_cost_egp": 0,
            "total_cost_egp": round(purchase_cost_egp, 2),
            "profit_egp": None,  # "Awaiting Weight"
            "has_weight": False,
        }
    
    # تكلفة الشحن (وزن بالجرام → كيلو)
    weight_kg = weight_grams / 1000.0
    shipping_cost_egp = weight_kg * shipping_price_per_kg_yuan * shipping_yuan_rate
    total_cost_egp = purchase_cost_egp + shipping_cost_egp
    profit_egp = selling_price_egp - total_cost_egp

    return {
        "purchase_cost_egp": round(purchase_cost_egp, 2),
        "shipping_cost_egp": round(shipping_cost_egp, 2),
        "total_cost_egp": round(total_cost_egp, 2),
        "profit_egp": round(profit_egp, 2),
        "has_weight": True,
    }


def profit_margin(selling_price_egp, total_cost_egp):
    """هامش الربح كنسبة مئوية من سعر البيع."""
    selling_price_egp = float(selling_price_egp or 0)
    if selling_price_egp == 0:
        return 0.0
    profit = selling_price_egp - float(total_cost_egp or 0)
    return round((profit / selling_price_egp) * 100, 1)


def payment_status(selling_price, deposit_paid):
    """تحديد حالة الدفع بناءً على المبلغ المدفوع."""
    selling_price = float(selling_price or 0)
    deposit_paid = float(deposit_paid or 0)
    
    if deposit_paid <= 0:
        return "Unpaid"
    elif deposit_paid >= selling_price:
        return "Paid In Full"
    else:
        return "Partially Paid"


def remaining_balance(selling_price, deposit_paid):
    """حساب الرصيد المتبقي."""
    return max(0, float(selling_price or 0) - float(deposit_paid or 0))
