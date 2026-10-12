"""보호자 대시보드 메인 — 기화

보호자(자녀) 한 명이 로그인하면 연결된 어르신(부모) 한 분의 상태만 본다.
시연용 데모 계정 4개로만 로그인한다 (회원가입 없음, src/auth.py).
화면 순서 (README 10장): 진행 표시 → 바이탈·실내기기 카드 → 위험도·승인·CCTV(두나 님 approval.py) → AutoHealing 로그
"""

import os
import sys
from html import escape
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
st.markdown(f"<style>{(FRONTEND_ROOT / 'assets/dashboard.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
st.markdown('<div class="care-brand">온기케어 <span>가족을 연결하는 돌봄 대시보드</span></div>', unsafe_allow_html=True)

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

st.markdown('''<section class="care-hero"><div><div class="care-tag">FAMILY CARE · 보호자 전용</div>
<h2>떨어져 있어도,<br>어르신의 하루를 함께 살펴보세요.</h2>
<p>몸 상태와 집 안 환경을 한눈에 확인하고 필요한 조치를 선택하세요.<br>
현재 서비스는 가상 데이터와 Mock 조치로 진행하는 시연입니다.</p></div>
<div class="care-orbit" aria-hidden="true">♡</div></section>''', unsafe_allow_html=True)

header, logout_column = st.columns([3, 1])   # 좁은 창에서도 "로그아웃" 글자가 잘리지 않게
with header:
    st.title(f"💚 {account.elder_name} 실시간 케어")
    st.markdown(
        f'<div class="care-account"><span>{escape(account.guardian_name)} 님으로 로그인했습니다</span>'
        f'<span class="care-account-badge">{escape(account.elder_name)} · 취약도 {escape(account.vulnerability)}</span></div>',
        unsafe_allow_html=True,
    )
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
    st.markdown('<div class="care-section">오늘의 돌봄 상태</div>', unsafe_allow_html=True)
    render_status_cards(run_response, backend_url)

st.divider()
render_autohealing_logs(backend_url, run_response.get("run_id") if isinstance(run_response, dict) else None)
st.markdown('<div class="care-footnote">시연용 가상 인물·측정값을 사용합니다. 기기 제어와 119 호출은 실제 실행이 아닌 Mock입니다.</div>', unsafe_allow_html=True)
