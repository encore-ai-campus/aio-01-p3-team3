"""보호자 대시보드 메인 — 기화

보호자(자녀) 한 명이 로그인하면 연결된 어르신(부모) 한 분의 상태만 본다.
시연용 데모 계정 4개로만 로그인한다 (회원가입 없음, src/auth.py).
화면 순서 (README 10장): 머리글·어르신 배너 → 진행 표시 → 위험도 배너·조치안·승인(두나 님 approval.py, 전체 폭)
→ 왼쪽 바이탈·주거 환경(CCTV 포함) 카드 / 오른쪽 실행 과정(AutoHealing) 카드
[팀 합의] 10/12 해든: 수언 님 시안(index-2.html) 느낌의 테마·머리글·어르신 배너·두 열 카드.
[팀 합의] 10/12 기화: 보호자가 처음 보는 화면 맨 위에 위험도와 승인할 조치안이 크게 보이도록 위험·승인 카드를 전체 폭으로 올림.
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
from src.components.theme import RISK_COLORS, apply_theme, brand_html  # noqa: E402

st.set_page_config(page_title="온기케어 | 어르신 실시간 케어", page_icon="💚", layout="wide")
apply_theme()

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


VULNERABILITY_CLASS = {"하": "low", "중": "medium", "상": "high"}   # 두나 님 #43 배지 색


def elder_banner(name: str, guardian: str, vulnerability: str, risk_level: str | None) -> str:
    initial = escape(name.split()[-1][:1] if name.split() else name[:1])
    if risk_level in RISK_COLORS:
        fg, bg = RISK_COLORS[risk_level]
        risk = f'<span style="color:{fg};background:{bg};">위험도 {escape(risk_level)}</span>'
    else:
        risk = '<span style="color:#fff;background:rgba(255,255,255,.14);">상태 확인 전</span>'
    return (f'<div class="ok-hero"><div class="ok-avatar">{initial}</div><div>'
            f'<div class="ok-hero-name">{escape(name)}</div>'
            f'<div class="ok-hero-sub">보호자 {escape(guardian)}'
            f'<span class="ok-vul care-vulnerability-{VULNERABILITY_CLASS.get(vulnerability, "unknown")}">'
            f'취약도 {escape(vulnerability)}</span></div></div>'
            f'<div class="ok-hero-risk">{risk}</div></div>')


brand_column, pill_column, logout_column = st.columns([3, 2, 0.8], vertical_alignment="center")
with brand_column:
    st.markdown(brand_html(), unsafe_allow_html=True)
with pill_column:
    st.markdown(f'<div class="ok-pills"><span class="ok-pill"><i></i>보호자 {escape(account.guardian_name)}</span></div>',
                unsafe_allow_html=True)
with logout_column:
    if st.button("로그아웃", use_container_width=True, key="logout_button"):
        log_out()
        st.rerun()

# 자리를 먼저 잡고, 두나 님 워크플로가 이번 실행 결과를 저장한 뒤에 채운다.
# (먼저 그리면 "상태 확인하기"를 누른 그 실행에서 이전 결과가 보이기 때문)
banner_area = st.container()
progress_area = st.container()

backend_url = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
# 첫 화면 맨 위: 위험도 배너 → 보호자 조치 승인(조치안·승인 버튼) → 결과 (전체 폭)
with st.container(key="alert_card"):
    st.markdown('<p class="ok-card-title">위험 판정과 보호자 승인</p>'
                '<div class="ok-card-sub">Emergency Agent · 기기 제어와 119는 승인 후 실행</div>',
                unsafe_allow_html=True)
    render_care_workflow(backend_url, profile_id=account.profile_id)

# 그 아래: 왼쪽 측정값 카드 / 오른쪽 AutoHealing 로그
left_column, right_column = st.columns([1.7, 1], gap="medium")

run_response = st.session_state.get("run_response")
run_mapping = run_response if isinstance(run_response, dict) else {}
emergency = run_mapping.get("emergency") if isinstance(run_mapping.get("emergency"), dict) else {}
risk_level = emergency.get("risk_level") or ("정상" if run_mapping.get("status") == "no_issue" else None)

with banner_area:
    st.markdown(elder_banner(account.elder_name, account.guardian_name, account.vulnerability, risk_level),
                unsafe_allow_html=True)
with progress_area:
    render_progress(run_response, st.session_state.get("approval_result"))
with left_column:
    render_status_cards(run_response, backend_url)
with right_column:
    with st.container(key="logs_card"):
        render_autohealing_logs(backend_url, run_mapping.get("run_id"))

st.markdown('<div class="care-footnote">시연용 가상 인물·측정값을 사용합니다. 기기 제어와 119 호출은 실제 실행이 아닌 Mock입니다.</div>',
            unsafe_allow_html=True)
