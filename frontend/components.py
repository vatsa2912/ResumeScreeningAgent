"""Reusable presentation helpers for the Shortlist dashboard."""
import streamlit as st

PAGES = ["Overview", "Job Setup", "Scoring Criteria", "Resume Screening", "Candidate Rankings"]


def navigate(page):
    st.session_state.page = page


def nav_button(label, page, *, key, primary=False, disabled=False):
    st.button(label, key=key, type="primary" if primary else "secondary", disabled=disabled,
              on_click=navigate, args=(page,), use_container_width=True)


def sidebar(online, stage):
    with st.sidebar:
        st.markdown('<div class="brand">Resume Screening Agent</div><div class="brand-sub">AI Resume Screening Platform</div>', unsafe_allow_html=True)
        st.divider()
        for name in PAGES:
            st.button(name, key=f"nav_{name}", on_click=navigate, args=(name,),
                      type="primary" if st.session_state.page == name else "secondary", use_container_width=True)
        st.divider()
        st.caption("BACKEND CONNECTION")
        if online:
            st.success("Connected")
        else:
            st.warning("Unavailable")
        st.caption(f"Workflow: {stage}")
        st.caption("Shortlist · University project")
        st.info("AI assists your review. Hiring decisions stay with people.")


def header(title, description, job, stage, online):
    st.markdown('<div class="overline">Shortlist / Recruitment workspace</div>', unsafe_allow_html=True)
    st.title(title)
    st.caption(description)
    job_name = job.get("title", "Untitled") if job else "No active job"
    st.caption(f"Active job: {job_name}  ·  Stage: {stage}  ·  Backend: {'Connected' if online else 'Unavailable'}")
    st.divider()


def empty_state(title, description, action, page, key):
    with st.container(border=True):
        st.subheader(title)
        st.write(description)
        nav_button(action, page, key=key, primary=True)


def score_bar(score):
    st.progress(min(max(float(score) / 10, 0.0), 1.0), text=f"{score:.1f} / 10")


def footer():
    st.markdown('<div class="footer">SHORTLIST &nbsp; · &nbsp; Human judgment belongs in every hiring decision.</div>', unsafe_allow_html=True)
