"""보호자 대시보드 메인: 실제 돌봄 실행·승인 API 연결."""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.approval import render_care_workflow


load_dotenv(Path(__file__).resolve().parents[1] / "config" / ".env")

st.set_page_config(
    page_title="어르신 실시간 케어",
    page_icon="💚",
    layout="wide",
)

st.title("어르신 실시간 케어")
st.caption("상태 확인 → 위험 판정 → 보호자 승인 → Mock 조치 → 결과 안내")

render_care_workflow(os.getenv("BACKEND_URL", "http://127.0.0.1:8000"))
