"""보호자 대시보드 메인 — 기화

보호자(자녀) 한 명이 로그인하면 연결된 어르신(부모) 한 분의 상태만 본다.
시연용 데모 계정 3개로만 로그인한다 (회원가입 없음, src/auth.py).
돌봄 실행·승인 화면은 두나 님 approval.py를 그대로 쓴다.
"""

import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))
load_dotenv(FRONTEND_ROOT / "config" / ".env")

from src.approval import render_care_workflow  # noqa: E402
from src.auth import current_account, load_accounts, log_out, render_login  # noqa: E402

st.set_page_config(page_title="어르신 실시간 케어", page_icon="💚", layout="wide")

try:
    accounts = load_accounts()
except ValueError as error:
    accounts = {}
    st.error(str(error))

account = current_account()
if account is None:
    if not accounts:
        st.error("데모 계정이 없습니다. frontend/config/.env에 DEMO_ACCOUNTS를 설정해 주세요.")
    else:
        render_login(accounts)
    st.stop()

header, logout_column = st.columns([3, 1])   # 좁은 창에서도 "로그아웃" 글자가 잘리지 않게
with header:
    st.title(f"💚 {account.elder_name} 실시간 케어")
    st.caption(f"{account.guardian_name} 님으로 로그인했습니다 · 상태 확인 → 위험 판정 → 보호자 승인 → 조치 → 결과 안내")
with logout_column:
    if st.button("로그아웃", use_container_width=True):
        log_out()
        st.rerun()

render_care_workflow(os.getenv("BACKEND_URL", "http://127.0.0.1:8000"), profile_id=account.profile_id)
