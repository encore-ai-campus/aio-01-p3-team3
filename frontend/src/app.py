"""온기케어 디자인과 팀의 실제 돌봄 승인 워크플로를 함께 제공하는 메인 화면."""

import os
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))
from src.approval import render_care_workflow

load_dotenv(FRONTEND_ROOT / "config" / ".env")

st.set_page_config(
    page_title="온기케어 | 보호자 대시보드",
    page_icon="💚",
    layout="wide",
)

# Keep the Streamlit shell from adding a visible drawer or outer padding around
# the design iframe. The HTML's own layout and spacing remain unchanged.
st.markdown(
    """
    <style>
      [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
      [data-testid="stStatusWidget"] { display: none !important; }
      [data-testid="stAppViewContainer"] .main .block-container,
      [data-testid="stMainBlockContainer"] {
        max-width: none;
        padding: 0 !important;
      }
      [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {
        gap: 0 !important;
      }
      iframe[title="st.iframe"] { display: block; }
    </style>
    """,
    unsafe_allow_html=True,
)

DESIGN_PATH = FRONTEND_ROOT / "index-2.html"

if not DESIGN_PATH.is_file():
    st.error(f"온기케어 디자인 HTML 파일을 찾을 수 없습니다: {DESIGN_PATH}")
else:
    try:
        design_html = DESIGN_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        st.error(f"온기케어 디자인 HTML 파일을 읽을 수 없습니다: {DESIGN_PATH}")
        st.exception(error)
    else:
        components.html(design_html, height=1360, scrolling=True)

st.divider()
st.subheader("실제 돌봄 승인 워크플로")
st.caption("위 HTML 디자인의 버튼은 미리보기용 모의 동작입니다. 실제 백엔드 조회와 보호자 승인은 아래 팀 워크플로에서 처리됩니다.")
render_care_workflow(os.getenv("BACKEND_URL", "http://127.0.0.1:8000"))
