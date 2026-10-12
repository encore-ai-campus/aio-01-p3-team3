"""보호자 대시보드 메인 — 기화

보호자(자녀) 한 명이 로그인하면 연결된 어르신(부모) 한 분의 상태만 본다.
시연용 데모 계정 4개로만 로그인한다 (회원가입 없음, src/auth.py).
화면 순서 (README 10장): 진행 표시 → 바이탈·실내기기 카드 → 위험도·승인·CCTV(두나 님 approval.py) → AutoHealing 로그
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
from src.components.cards import render_status_cards  # noqa: E402
from src.components.logs import render_autohealing_logs  # noqa: E402
from src.components.progress import render_progress  # noqa: E402

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
    st.caption(f"{account.guardian_name} 님으로 로그인했습니다 · {account.elder_name} 취약도 {account.vulnerability}")
with logout_column:
    if st.button("로그아웃", use_container_width=True):
        log_out()
        st.rerun()

# 진행 표시·카드 자리를 먼저 잡고, 두나 님 워크플로가 이번 실행 결과를 저장한 뒤에 채운다.
# (먼저 그리면 "상태 확인하기"를 누른 그 실행에서 이전 결과가 보이기 때문)
status_area = st.container()

backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
render_care_workflow(backend_url, profile_id=account.profile_id)

run_response = st.session_state.get("run_response")
with status_area:
    render_progress(run_response, st.session_state.get("approval_result"))
    render_status_cards(run_response)

st.divider()
render_autohealing_logs(backend_url, run_response.get("run_id") if isinstance(run_response, dict) else None)
