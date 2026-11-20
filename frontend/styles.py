"""Dashboard styling; interactive controls remain native Streamlit widgets."""
import streamlit as st


def apply_styles():
    st.markdown("""
<style>
:root { color-scheme: light; }
.stApp { background: #F8FAFC; color: #0F172A; font-family: Inter, 'Segoe UI', sans-serif; }
header[data-testid="stHeader"] { background: #F8FAFC; }
section[data-testid="stSidebar"] { background: #fff; border-right: 1px solid #E2E8F0; }
.block-container { max-width: 1240px; padding-top: 2.5rem; padding-bottom: 3rem; }
h1,h2,h3 { color: #0F172A; letter-spacing: -.035em; }
h1 { font-size: 2rem !important; } h2 { font-size: 1.3rem !important; }
p, label, div[data-testid="stCaptionContainer"] { overflow-wrap: anywhere; }
.brand { font-size: 1.2rem; font-weight: 800; letter-spacing: .07em; color: #4F46E5; padding: .7rem 0 .15rem; }
.brand-sub, .muted { color: #64748B; font-size: .85rem; line-height: 1.55; }
.overline { color: #4F46E5; font-size: .72rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.page-sub { color: #64748B; margin-top: -.5rem; margin-bottom: 1.2rem; }
.footer { border-top: 1px solid #E2E8F0; color: #64748B; font-size: .8rem; padding-top: 1.2rem; margin-top: 3rem; }
div[data-testid="stMetric"], div[data-testid="stVerticalBlockBorderWrapper"] > div { background: #fff; border: 1px solid #E2E8F0; border-radius: 14px; box-shadow: 0 4px 16px rgba(15,23,42,.035); }
div[data-testid="stMetric"] { padding: 1.1rem; min-height: 105px; }
div[data-testid="stMetricLabel"] { color: #64748B; }
div[data-testid="stMetricValue"] { font-size: 1.45rem; }
div[data-testid="stExpander"] details { background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; }
div[data-testid="stFileUploaderDropzone"] { background: #F8FAFC; border: 1px dashed #A5B4FC; border-radius: 12px; }
div.stButton button[kind="primary"], div[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] { background: #4F46E5; border-color: #4F46E5; color: #fff; }
div.stButton button[kind="primary"]:hover, div[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]:hover { background: #4338CA; border-color: #4338CA; color: #fff; }
div.stButton button, div[data-testid="stFormSubmitButton"] button { border-radius: 9px; transition: box-shadow .15s ease, background .15s ease; }
div.stButton button:hover { box-shadow: 0 4px 12px rgba(79,70,229,.14); }
:focus-visible { outline: 2px solid #4F46E5 !important; outline-offset: 2px; }
@media (max-width: 700px) { .block-container { padding-top: 1.5rem; } h1 { font-size: 1.65rem !important; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; } }
</style>
""", unsafe_allow_html=True)
