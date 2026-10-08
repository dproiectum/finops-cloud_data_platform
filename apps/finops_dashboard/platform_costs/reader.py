"""Private GCS reader using Cloud Run ADC; no keys, public URL or silent fallback."""

import json
import os
import re
from urllib.parse import quote

import streamlit as st

from .model import load_snapshot as load_bundled
from .snapshot import read_payload


MAX_BYTES = 4 * 1024 * 1024


def storage_url(uri):
    match = re.fullmatch(r"gs://([a-z0-9][a-z0-9_.-]{1,220}[a-z0-9])/(platform_costs/published/latest\.json)", uri)
    if not match:
        raise ValueError("Configure the dedicated Platform Costs published object.")
    bucket, object_name = match.groups()
    return f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(object_name, safe='')}?alt=media"


@st.cache_data(ttl=300, show_spinner=False)
def download_payload(uri):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    url = storage_url(uri)
    try:
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
        with AuthorizedSession(credentials) as session:
            with session.get(url, timeout=20, stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError("Platform cost object is unavailable.")
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise ValueError("Platform cost snapshot exceeds the size limit.")
                return json.loads(content)
    except Exception as exc:
        raise ValueError("Unable to read the private platform cost snapshot.") from exc


def load_snapshot():
    mode = os.getenv("FINOPS_PLATFORM_COSTS_MODE", "bundled").strip()
    if mode == "bundled":
        return load_bundled()
    if mode != "gcs":
        raise ValueError("FINOPS_PLATFORM_COSTS_MODE must be bundled or gcs.")
    uri = os.getenv("FINOPS_PLATFORM_COSTS_GCS_URI", "").strip()
    try:
        max_age = int(os.getenv("FINOPS_PLATFORM_COSTS_MAX_AGE_HOURS", "48"))
    except ValueError as exc:
        raise ValueError("Invalid snapshot freshness configuration.") from exc
    if not 1 <= max_age <= 168:
        raise ValueError("Snapshot freshness must be between 1 and 168 hours.")
    return read_payload(download_payload(uri), remote=True, max_age_hours=max_age)
