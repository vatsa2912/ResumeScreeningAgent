import streamlit as st

from api_client import backend_online, request, valid_job, valid_rankings
from components import display_text, empty_state, footer, header, nav_button, score_bar, sidebar
from screening import render_screening
from styles import apply_styles

st.set_page_config(page_title="Candidate Screening Hub | AI Resume Screening", page_icon=":material/groups:", layout="wide")
apply_styles()

DEFAULTS = {
    "page": "Overview", "job": None, "rubric_version": 0, "rankings": None,
    "rankings_stale": False, "eval_result": None, "weights": [],
    "draft_title": "", "draft_description": "", "notice": None,
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


def remember(widget, target):
    st.session_state[target] = st.session_state[widget]


def remember_weight(index, key):
    st.session_state.weights[index] = st.session_state[key]


def stage_name():
    if not st.session_state.job:
        return "Job setup"
    if st.session_state.rankings:
        return "Review rankings"
    if st.session_state.eval_result:
        return "Resume screening"
    return "Review criteria"


def refresh_rankings(job_id):
    data, error = request("GET", f"/jobs/{job_id}/rankings")
    if error:
        return error
    if not valid_rankings(data):
        return "The screening service returned incomplete ranking data."
    st.session_state.rankings = data["rankings"]
    # The API does not return rubric versions, so refreshing cannot establish freshness.
    return None


def changed_weights(job):
    return any(float(item["weight"]) != float(weight)
               for item, weight in zip(job["rubric"], st.session_state.weights))


online = backend_online()
job = st.session_state.job
stage = stage_name()
sidebar(online, stage)
page = st.session_state.page
descriptions = {
    "Overview": "Screen resumes with clear criteria and evidence-backed scores.",
    "Job Setup": "Describe the role and generate job-specific scoring criteria.",
    "Scoring Criteria": "Review and customize how candidates will be evaluated.",
    "Resume Screening": "Add candidate resumes for AI evaluation.",
    "Candidate Rankings": "Compare candidates using job-specific scoring criteria.",
}
header("Welcome to Resume Screening Agent" if page == "Overview" else page, descriptions[page], job, stage, online)
if st.session_state.notice:
    st.success(st.session_state.notice)
    st.session_state.notice = None

if page == "Overview":
    rankings = st.session_state.rankings
    cols = st.columns(4)
    cols[0].metric("Active job", job["title"] if job else "No active job")
    cols[1].metric("Scoring criteria", str(len(job["rubric"])) if job else "Not available")
    cols[2].metric("Evaluated candidates", str(len(rankings)) if rankings is not None else "Not available")
    cols[3].metric("Highest score", f"{max(r['total_score'] for r in rankings):.1f} / 10" if rankings else "Not available")
    if st.session_state.rankings_stale:
        st.warning("These rankings were generated using an earlier version of the scoring criteria. Re-evaluate resumes to get updated scores.")
    st.subheader("Your workflow")
    steps = [("01", "Job Setup"), ("02", "Review Criteria"), ("03", "Upload Resumes"), ("04", "Review Rankings")]
    current = 0 if not job else 3 if rankings else 2 if st.session_state.eval_result else 1
    for col, (number, label), i in zip(st.columns(4), steps, range(4)):
        with col:
            with st.container(border=True):
                st.caption(f"{number} / {'COMPLETE' if i < current else 'CURRENT' if i == current else 'PENDING'}")
                st.write(label)
    st.subheader("Quick actions")
    actions = st.columns(4)
    for col, (label, dest) in zip(actions, [("Create a job", "Job Setup"), ("Review criteria", "Scoring Criteria"), ("Upload resumes", "Resume Screening"), ("View rankings", "Candidate Rankings")]):
        with col:
            nav_button(label, dest, key=f"quick_{dest}")
    if not job:
        st.subheader("Getting started")
        empty_state("Build your first Candidate Screening Hub", "Start with a job description. Candidate Screening Hub will help you define criteria before you screen candidates.", "Create Your First Job", "Job Setup", "first_job")

elif page == "Job Setup":
    left, right = st.columns([1.65, 1], gap="large")
    with left:
        with st.container(border=True):
            st.subheader("Role details")
            st.caption("Include responsibilities and qualifications in the description.")
            if "title_widget" not in st.session_state:
                st.session_state.title_widget = st.session_state.draft_title
            if "description_widget" not in st.session_state:
                st.session_state.description_widget = st.session_state.draft_description
            st.text_input("Job title", key="title_widget", placeholder="e.g. Senior Product Designer", on_change=remember, args=("title_widget", "draft_title"))
            st.text_area("Job description", key="description_widget", height=260, placeholder="Describe the role, responsibilities, required skills and qualifications...", on_change=remember, args=("description_widget", "draft_description"))
            confirmed = True
            if job:
                st.warning("Creating a new job replaces the active job and its results in this session. Existing backend records remain stored.")
                confirmed = st.checkbox("I understand and want to replace the active job")
            if st.button("Generate Scoring Criteria", type="primary", disabled=not confirmed):
                title = st.session_state.draft_title.strip()
                description = st.session_state.draft_description.strip()
                if not title or not description:
                    st.error("Enter both a job title and a job description.")
                else:
                    with st.spinner("Generating criteria with the AI model. This may take a few minutes..."):
                        data, error = request("POST", "/jobs", json={"title": title, "raw_description": description}, timeout=300)
                    if error:
                        st.error(display_text(error))
                    elif not valid_job(data):
                        st.error("The screening service returned incomplete job or criteria data.")
                    else:
                        st.session_state.update(job=data, rankings=None, rankings_stale=False, eval_result=None,
                                                weights=[round(item["weight"]) for item in data["rubric"]],
                                                page="Scoring Criteria", notice="Scoring criteria generated. Review them below.")
                        st.session_state.rubric_version += 1
                        st.rerun()
    with right:
        if not job:
            with st.form("reopen_job"):
                st.subheader("Reopen a saved job")
                saved_id = st.number_input("Saved job ID", min_value=1, value=None, step=1)
                if st.form_submit_button("Reopen saved job") and saved_id:
                    data, error = request("GET", f"/jobs/{saved_id}")
                    if error:
                        st.error(display_text(error))
                    elif not valid_job(data) or data["id"] != saved_id:
                        st.error("The screening service returned incomplete job data.")
                    else:
                        st.session_state.update(job=data, rankings=None, rankings_stale=False, eval_result=None,
                                                weights=[round(item["weight"]) for item in data["rubric"]])
                        st.session_state.rubric_version += 1
                        ranking_error = refresh_rankings(saved_id)
                        st.session_state.page = "Resume Screening"
                        st.session_state.notice = f"Reopened job #{saved_id}."
                        if ranking_error:
                            st.session_state.notice += " Open Candidate Rankings to refresh the saved scores."
                        st.rerun()
        with st.container(border=True):
            st.subheader("How it works")
            st.markdown("**01 · Describe the role**  \nShare the requirements that matter.")
            st.markdown("**02 · Review the criteria**  \nAdjust the weights before screening.")
            st.markdown("**03 · Evaluate candidates**  \nReview scores and supporting explanations.")
        st.info("Tip: Specify distinct skills and qualifications to make the generated criteria more useful.")

elif page == "Scoring Criteria":
    if not job:
        empty_state("No criteria yet", "Create a job to generate your scoring criteria.", "Go to Job Setup", "Job Setup", "criteria_empty")
    else:
        if len(st.session_state.weights) != len(job["rubric"]):
            st.session_state.weights = [round(item["weight"]) for item in job["rubric"]]
        for i, item in enumerate(job["rubric"]):
            with st.container(border=True):
                left, right = st.columns([3, 1])
                with left:
                    st.subheader(display_text(item["criterion"]))
                    st.write(display_text(item["description"]))
                    if item.get("how_to_detect"):
                        st.caption("Look for: " + display_text(str(item["how_to_detect"])))
                with right:
                    key = f"weight_{st.session_state.rubric_version}_{i}"
                    if key not in st.session_state:
                        st.session_state[key] = st.session_state.weights[i]
                    st.number_input(f"Weight for {display_text(item['criterion'])} (%)", min_value=0, max_value=100, step=1, key=key, on_change=remember_weight, args=(i, key))
                    st.progress(st.session_state.weights[i] / 100, text=f"{st.session_state.weights[i]}% weight")
        total = sum(st.session_state.weights)
        with st.container(border=True):
            a, b, c = st.columns(3)
            a.metric("Total weight", f"{total}%")
            b.metric("Criteria", len(job["rubric"]))
            c.metric("Status", "Ready" if total == 100 else "Will rebalance")
            st.progress(min(total / 100, 1.0), text="Weights are balanced to 100% by the backend when saved.")
        if st.button("Save Scoring Criteria", type="primary"):
            rubric = [{**item, "weight": weight} for item, weight in zip(job["rubric"], st.session_state.weights)]
            was_changed = changed_weights(job)
            with st.spinner("Saving criteria..."):
                data, error = request("PUT", f"/jobs/{job['id']}/rubric", json={"rubric": rubric})
            if error:
                st.error(display_text(error))
            elif not valid_job(data):
                st.error("The screening service returned incomplete criteria data.")
            else:
                if was_changed and (st.session_state.rankings or st.session_state.eval_result):
                    st.session_state.rankings_stale = True
                st.session_state.job = data
                st.session_state.weights = [round(item["weight"]) for item in data["rubric"]]
                st.session_state.rubric_version += 1
                st.session_state.notice = "Scoring criteria saved and balanced."
                st.rerun()
        nav_button("Continue to Resume Screening →", "Resume Screening", key="criteria_next")

elif page == "Resume Screening":
    if not job:
        empty_state("No active job", "Create a job before uploading candidate resumes.", "Go to Job Setup", "Job Setup", "upload_empty")
    else:
        if changed_weights(job):
            st.warning("You have unsaved weight changes. Save your criteria before evaluating candidates.")
        render_screening(job, changed_weights(job), refresh_rankings)

elif page == "Candidate Rankings":
    if not job:
        empty_state("No rankings yet", "Create a job and evaluate resumes to Discover the Right Talent.", "Go to Job Setup", "Job Setup", "rank_no_job")
    else:
        if st.button("Refresh rankings"):
            error = refresh_rankings(job["id"])
            if error:
                st.error(display_text(error))
        if st.session_state.rankings_stale:
            st.warning("These rankings were generated using an earlier version of the scoring criteria. Re-evaluate resumes to get updated scores.")
            st.caption("Previous scores remain in the backend after re-evaluation, and the API does not identify their criteria version. This warning remains until a new job is created.")
        if changed_weights(job):
            st.info("You have unsaved criteria changes. Existing scores use the saved criteria.")
        rankings = st.session_state.rankings
        if rankings is None or not rankings:
            empty_state("No candidates evaluated yet", "Upload resumes to Discover the Right Talent.", "Go to Resume Screening", "Resume Screening", "rank_empty")
        else:
            a, b, c, d = st.columns(4)
            a.metric("Evaluated candidates", len(rankings))
            b.metric("Highest score", f"{max(r['total_score'] for r in rankings):.1f} / 10")
            c.metric("Average score", f"{sum(r['total_score'] for r in rankings) / len(rankings):.1f} / 10")
            d.metric("Scoring criteria", len(job["rubric"]))
            order = st.selectbox("Sort candidates", ["Original ranking", "Highest score", "Lowest score", "Filename"])
            indexed = list(enumerate(rankings, start=1))
            if order == "Highest score":
                indexed.sort(key=lambda pair: pair[1]["total_score"], reverse=True)
            elif order == "Lowest score":
                indexed.sort(key=lambda pair: pair[1]["total_score"])
            elif order == "Filename":
                indexed.sort(key=lambda pair: pair[1]["filename"].casefold())
            for rank, entry in indexed:
                with st.container(border=True):
                    st.caption(f"RANK {rank:02d}")
                    st.text(entry["filename"])
                    score_bar(entry["total_score"])
                    st.write(display_text(entry["summary"]))
                    with st.expander("View Details"):
                        st.write("Criterion breakdown")
                        for criterion in entry["criteria_breakdown"]:
                            st.write(display_text(criterion["criterion"]))
                            score_bar(criterion["score"])
                            st.write(display_text(criterion["justification"]))
                            if isinstance(criterion.get("evidence"), str) and criterion["evidence"]:
                                st.caption("Evidence: " + display_text(criterion["evidence"]))

footer()
