# -*- coding: utf-8 -*-
"""
storage.py
رفع وعرض صور الإيصالات على Supabase Storage (bucket: receipts).
المفاتيح تُقرأ من إعدادات Streamlit (Secrets):
    supabase_url = "https://xxxx.supabase.co"
    supabase_key = "secret_key_here"   # المفتاح السري (secret) للرفع من السيرفر
"""

import time
import requests
import streamlit as st

BUCKET = "receipts"


def _cfg():
    """يرجّع (url, key) من الإعدادات أو (None, None) لو مش متسجلة."""
    try:
        url = st.secrets["supabase_url"].rstrip("/")
        key = st.secrets["supabase_key"]
        return url, key
    except Exception:
        return None, None


def is_enabled():
    url, key = _cfg()
    return bool(url and key)


def upload_image(folder, file_bytes, filename, content_type="image/jpeg"):
    """يرفع صورة داخل مجلد معيّن. يرجّع (نجاح, رسالة)."""
    url, key = _cfg()
    if not (url and key):
        return False, "خدمة تخزين الصور غير مفعّلة. أضف supabase_url و supabase_key في الإعدادات."
    # اسم فريد لتفادي التكرار
    safe = filename.replace(" ", "_").replace("/", "_").replace("\\", "_")
    path = f"{folder}/{int(time.time()*1000)}_{safe}"
    endpoint = f"{url}/storage/v1/object/{BUCKET}/{path}"
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    try:
        r = requests.post(endpoint, headers=headers, data=file_bytes, timeout=30)
        if r.status_code in (200, 201):
            return True, "تم رفع الصورة."
        return False, f"فشل الرفع ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return False, f"خطأ في الاتصال: {e}"


def list_images(folder):
    """يرجّع قائمة روابط عامة لصور مجلد معيّن."""
    url, key = _cfg()
    if not (url and key):
        return []
    endpoint = f"{url}/storage/v1/object/list/{BUCKET}"
    headers = {"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": "application/json"}
    body = {"prefix": f"{folder}/", "limit": 100, "sortBy": {"column": "name", "order": "asc"}}
    try:
        r = requests.post(endpoint, headers=headers, json=body, timeout=30)
        if r.status_code != 200:
            return []
        files = r.json()
        links = []
        for f in files:
            name = f.get("name")
            if not name:
                continue
            public = f"{url}/storage/v1/object/public/{BUCKET}/{folder}/{name}"
            links.append((name, public))
        return links
    except Exception:
        return []


def delete_image(folder, name):
    url, key = _cfg()
    if not (url and key):
        return False
    endpoint = f"{url}/storage/v1/object/{BUCKET}/{folder}/{name}"
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    try:
        r = requests.delete(endpoint, headers=headers, timeout=30)
        return r.status_code in (200, 204)
    except Exception:
        return False
