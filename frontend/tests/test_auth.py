"""시연용 데모 계정 로그인 테스트 — 기화"""

import pytest
from streamlit.testing.v1 import AppTest

from src import approval
from src.auth import DemoAccount, authenticate, log_in, log_out, parse_accounts

RAW = "childA:pw-a:profile-01,childB:pw-b:profile-02,childC:pw-c:profile-03,childD:pw-d:profile-04"


def test_parse_four_demo_accounts():
    accounts = parse_accounts(RAW)
    assert set(accounts) == {"childA", "childB", "childC", "childD"}
    assert accounts["childB"].profile_id == "profile-02"
    assert accounts["childB"].guardian_name == "자녀 B" and accounts["childB"].elder_name == "어르신 B"
    assert accounts["childD"].profile_id == "profile-04" and accounts["childD"].elder_name == "어르신 D"


@pytest.mark.parametrize("raw", ["childA:pw-a", "childA::profile-01", "childA:pw:profile-99",
                                 "childA:pw:profile-01,childA:pw2:profile-02"])
def test_bad_account_config_is_rejected(raw):
    with pytest.raises(ValueError):
        parse_accounts(raw)


def test_missing_config_gives_no_accounts():
    assert parse_accounts(None) == {} and parse_accounts("") == {}


def test_authenticate():
    accounts = parse_accounts(RAW)
    assert authenticate(accounts, "childA", "pw-a").profile_id == "profile-01"
    assert authenticate(accounts, " childA ", "pw-a") is not None      # 아이디 앞뒤 공백 허용
    assert authenticate(accounts, "childA", "pw-b") is None            # 다른 사람 비밀번호
    assert authenticate(accounts, "nobody", "pw-a") is None


def test_switching_guardian_clears_previous_screen():
    state = {"run_response": {"run_id": "run-1"}, "emergency": {}, "approval_result": {}}
    log_in(DemoAccount("childB", "pw-b", "profile-02"), state)
    assert state == {"guardian": DemoAccount("childB", "pw-b", "profile-02")}
    log_out(state)
    assert state == {}


# ---------- 화면 (Streamlit AppTest) ----------

def app_with_accounts(monkeypatch, raw=RAW):
    monkeypatch.setenv("DEMO_ACCOUNTS", raw)
    return AppTest.from_file("../src/app.py").run()


def log_in_as(app, username, password):
    app.text_input[0].input(username)
    app.text_input[1].input(password)
    return next(b for b in app.button if b.label == "로그인").click().run()


def test_login_screen_comes_first(monkeypatch):
    app = app_with_accounts(monkeypatch)
    assert not app.exception
    assert any(b.label == "로그인" for b in app.button)
    assert not any(b.label == "상태 확인하기" for b in app.button)


def test_wrong_password_stays_on_login(monkeypatch):
    app = log_in_as(app_with_accounts(monkeypatch), "childA", "wrong")
    assert any("맞지 않습니다" in e.value for e in app.error)
    assert not any(b.label == "상태 확인하기" for b in app.button)


def test_guardian_sees_only_own_elder_and_runs_with_that_profile(monkeypatch):
    submitted = []

    def fake_run(backend_url, profile_id, scenario, fault):
        submitted.append(profile_id)
        return {"run_id": "run-b", "status": "no_issue", "current_step": "완료", "message": "이상 없음"}

    monkeypatch.setattr(approval, "request_care_run", fake_run)
    app = log_in_as(app_with_accounts(monkeypatch), "childB", "pw-b")
    assert not app.exception
    assert any("어르신 B" in m.value for m in app.markdown)   # 어르신 배너 (10/12 해든: 제목 → 배너)
    assert not any(s.label == "어르신" for s in app.selectbox)        # 어르신 선택 없음
    next(b for b in app.button if b.label == "상태 확인하기").click().run()
    assert submitted == ["profile-02"]


def test_logout_returns_to_login(monkeypatch):
    app = log_in_as(app_with_accounts(monkeypatch), "childC", "pw-c")
    app = next(b for b in app.button if b.label == "로그아웃").click().run()
    assert any(b.label == "로그인" for b in app.button)


def test_missing_accounts_shows_setup_message(monkeypatch):
    app = app_with_accounts(monkeypatch, raw="")
    assert any("DEMO_ACCOUNTS" in e.value for e in app.error)
