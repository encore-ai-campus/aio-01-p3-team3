"""시연용 데모 계정 로그인 (회원가입 없음) — 기화

보호자(자녀) 한 명이 어르신(부모) 한 분을 보는 화면을 시연하기 위한 간단한 로그인이다.
계정 4개는 config/.env의 DEMO_ACCOUNTS에만 두고 저장소에는 올리지 않는다.
  형식: 아이디:비밀번호:프로필ID 를 쉼표로 구분
  예)   DEMO_ACCOUNTS=childA:비밀번호A:profile-01,childB:비밀번호B:profile-02,childC:비밀번호C:profile-03,childD:비밀번호D:profile-04

⚠️ 실제 보안 기능이 아니다. 백엔드는 요청자를 확인하지 않으므로 시연 화면 구분 용도로만 쓴다.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import MutableMapping
from dataclasses import dataclass

import streamlit as st

# 프로필 ID → 화면에 보일 이름 (가상 인물). docs/scenarios.md 3장 프로필과 같다.
PROFILE_DISPLAY = {
    "profile-01": {"guardian": "A", "elder": "어르신 A", "vulnerability": "상"},
    "profile-02": {"guardian": "B", "elder": "어르신 B", "vulnerability": "중"},
    "profile-03": {"guardian": "C", "elder": "어르신 C", "vulnerability": "하"},
    "profile-04": {"guardian": "D", "elder": "어르신 D", "vulnerability": "상"},
}
SESSION_KEY = "guardian"
# 로그아웃하거나 다른 보호자로 바꿀 때 지우는 화면 상태 (두나 님 approval.py가 저장하는 키 포함)
CLEAR_ON_LOGOUT = ("run_response", "run_id", "care_status", "emergency", "approval_result")


@dataclass(frozen=True)
class DemoAccount:
    username: str
    password: str
    profile_id: str

    @property
    def guardian_name(self) -> str:
        return PROFILE_DISPLAY[self.profile_id]["guardian"]

    @property
    def elder_name(self) -> str:
        return PROFILE_DISPLAY[self.profile_id]["elder"]

    @property
    def vulnerability(self) -> str:
        return PROFILE_DISPLAY[self.profile_id]["vulnerability"]


def parse_accounts(raw: str | None) -> dict[str, DemoAccount]:
    """DEMO_ACCOUNTS 문자열 → {아이디: 계정}. 형식이 틀리면 ValueError."""
    accounts: dict[str, DemoAccount] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ValueError("DEMO_ACCOUNTS 형식은 '아이디:비밀번호:프로필ID'를 쉼표로 구분해야 합니다.")
        username, password, profile_id = (part.strip() for part in parts)
        if profile_id not in PROFILE_DISPLAY:
            raise ValueError(f"DEMO_ACCOUNTS에 지원하지 않는 프로필이 있습니다: {profile_id}")
        if username in accounts:
            raise ValueError(f"DEMO_ACCOUNTS에 같은 아이디가 두 번 있습니다: {username}")
        accounts[username] = DemoAccount(username, password, profile_id)
    return accounts


def load_accounts() -> dict[str, DemoAccount]:
    return parse_accounts(os.getenv("DEMO_ACCOUNTS"))


def authenticate(accounts: dict[str, DemoAccount], username: str, password: str) -> DemoAccount | None:
    account = accounts.get(username.strip())
    if account is None:
        return None
    # 시간 차이로 비밀번호를 추측하지 못하게 비교 (시연용이지만 기본은 지킨다)
    if not hmac.compare_digest(account.password.encode("utf-8"), password.encode("utf-8")):
        return None
    return account


def current_account(state: MutableMapping | None = None) -> DemoAccount | None:
    state = st.session_state if state is None else state
    value = state.get(SESSION_KEY)
    return value if isinstance(value, DemoAccount) else None


def log_in(account: DemoAccount, state: MutableMapping | None = None) -> None:
    state = st.session_state if state is None else state
    for key in CLEAR_ON_LOGOUT:
        state.pop(key, None)
    state[SESSION_KEY] = account


def log_out(state: MutableMapping | None = None) -> None:
    state = st.session_state if state is None else state
    for key in (SESSION_KEY, *CLEAR_ON_LOGOUT):
        state.pop(key, None)


def render_login(accounts: dict[str, DemoAccount]) -> None:
    """로그인 화면. 성공하면 세션에 계정을 저장하고 화면을 다시 그린다."""
    st.title("💚 어르신 실시간 케어")
    st.caption("보호자 로그인 · 시연용 데모 계정만 사용할 수 있습니다 (회원가입 없음)")

    with st.form("login_form"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)

    if submitted:
        account = authenticate(accounts, username, password)
        if account is None:
            st.error("아이디 또는 비밀번호가 맞지 않습니다.")
        else:
            log_in(account)
            st.rerun()
