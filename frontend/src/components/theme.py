"""온기케어 화면 테마 — 해든 (수언 님 시안 index-2.html의 색·글꼴·카드 모양을 Streamlit에 입힘)

[팀 합의] 시안은 HTML을 iframe으로 통째로 띄우면 버튼이 백엔드를 부르지 못해,
같은 느낌을 CSS로 Streamlit 위젯에 입히는 방식으로 옮겼다. 데이터·판단 로직은 그대로다.
CSS 본문은 assets/dashboard.css(두나 님 #43 파일)에 있다. 카드는 st.container(key=...)가 붙이는 .st-key-<key> 클래스로 골라 꾸민다.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

# 시안에서 뽑은 색. 다른 파일에서 HTML을 그릴 때도 이 값을 쓴다.
COLORS = {
    "bg": "#f4f0e8",
    "surface": "#fffdf9",
    "line": "#ebe4d8",
    "ink": "#25313a",
    "muted": "#7b8086",
    "slate": "#3a4a54",
    "green": "#1f6b4f",
    "mint": "#dcefe6",
    "red": "#d03d2f",
    "red_soft": "#f6e2df",
    "red_line": "#ebb8b2",
    "amber": "#c8793f",
    "amber_soft": "#f8eadb",
    "gray_soft": "#eeebe6",
}

# 위험도(README 4단계) → (글자색, 배경색)
RISK_COLORS = {
    "정상": (COLORS["green"], COLORS["mint"]),
    "주의": (COLORS["amber"], COLORS["amber_soft"]),
    "경고": (COLORS["red"], COLORS["red_soft"]),
    "위급": ("#ffffff", COLORS["red"]),
}

CSS_PATH = Path(__file__).resolve().parents[2] / "assets" / "dashboard.css"   # 색을 바꾸면 COLORS도 같이


def apply_theme() -> None:
    """모든 화면 맨 앞에서 한 번 부른다."""
    # st.html은 <style>만 있으면 자리를 차지하지 않고 페이지에 CSS만 넣는다.
    st.html(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>")


def card_header(title: str, subtitle: str = "", badge: str = "", badge_colors: tuple[str, str] | None = None) -> None:
    """카드 맨 위 제목 줄. badge_colors는 (글자색, 배경색)."""
    badge_html = ""
    if badge:
        fg, bg = badge_colors or (COLORS["green"], COLORS["mint"])
        badge_html = f'<span class="ok-badge" style="color:{fg};background:{bg};">{escape(badge)}</span>'
    sub_html = f'<div class="ok-card-sub">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="ok-card-head"><div><p class="ok-card-title">{escape(title)}</p>{sub_html}</div>{badge_html}</div>',
        unsafe_allow_html=True,
    )


def brand_html() -> str:
    return '<div class="ok-brand"><small>senior safety network</small><b>✱ 온기케어</b></div>'
