"""Ponto de entrada do Streamlit Community Cloud."""
import hashlib
import hmac
from datetime import datetime
from pathlib import Path
import time

import pandas as pd
import streamlit as st

from cloud_runtime import Runtime, account_from_session
from settings import AppError
from storage import EXCEL_NAME, JSON_NAME

st.set_page_config(page_title="Instagram Insights", page_icon="📊", layout="wide")


def secret(name):
    try:
        return str(st.secrets.get(name, "")).strip()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


def authorize():
    expected = secret("DASHBOARD_PASSWORD")
    if not expected or len(expected) < 12 or expected.startswith("SUBSTITUA_"):
        st.info("Configure DASHBOARD_PASSWORD nos Secrets do Streamlit, usando uma senha com pelo menos 12 caracteres.")
        return False
    fingerprint = hashlib.sha256(expected.encode()).hexdigest()
    if st.session_state.get("authorized") == fingerprint:
        return True
    st.title("Instagram Insights")
    st.caption("Acesso da equipe")
    with st.form("login", clear_on_submit=True):
        entered = st.text_input("Senha do dashboard", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if submitted:
        until = st.session_state.get("login_retry_after", 0)
        if time.monotonic() < until:
            st.error("Aguarde alguns segundos antes de tentar novamente.")
        elif hmac.compare_digest(entered.encode(), expected.encode()):
            st.session_state["authorized"] = fingerprint
            st.rerun()
        else:
            st.session_state["login_retry_after"] = time.monotonic() + 5
            st.error("Senha incorreta.")
    return False


@st.cache_resource
def shared_runtime(account_id):
    return Runtime(account_id, Path(__file__).resolve().parent / ".runtime" / account_id)


def fmt(value):
    return "Indisponível" if value is None else f"{value:,.0f}".replace(",", ".")


def display_date(value):
    return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M") if value else "Data não informada"


def main():
    if not authorize():
        return
    try:
        account = account_from_session(secret("INSTAGRAM_SESSIONID"))
        runtime = shared_runtime(account)
    except AppError as error:
        st.error(str(error))
        return
    from cloud_ui import run_dashboard
    run_dashboard(runtime, account, secret)

main()
