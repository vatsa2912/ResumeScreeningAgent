import streamlit as st
import requests

API_BASE_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Resume Screening Agent", layout="wide")
st.title("AI Resume Screening Agent")

# Initialize session state - this survives across re-runs, unlike normal variables    
if "job" not in st.session_state:
    st.session_state.job = None
if "rubric_version" not in st.session_state:
    st.session_state.rubric_version = 0

st.header("Step 1: Job Description")

title = st.text_input("Job Title", value="Full Stack Developer")
description = st.text_area("Job Description", height=200)

if st.button("Generate Rubric"):
    if not description.strip():
        st.error("Please enter a job description.")
    else:
        with st.spinner("Generating rubric... this may take a minute."):
            response = requests.post(
                f"{API_BASE_URL}/jobs",
                json={"title": title, "raw_description": description}
            )

        if response.status_code == 200:
            st.session_state.job = response.json()
            st.session_state.rubric_version += 1
            st.success(f"Job created (id={st.session_state.job['id']}) with {len(st.session_state.job['rubric'])} criteria")
        else:
            st.error(f"Failed to create job: {response.text}")

if st.session_state.job is not None:
    st.header("Step 2: Review & Edit Rubric")

    job = st.session_state.job
    rubric = job["rubric"]

    edited_rubric = []
    total_weight = 0

    for i, item in enumerate(rubric):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{item['criterion']}** — {item['description']}")
        with col2:
            new_weight = st.number_input(
                f"Weight (%)", min_value=0, max_value=100, value=item["weight"], key=f"weight_{st.session_state.rubric_version}_{i}"
            )

        edited_item = dict(item)
        edited_item["weight"] = new_weight
        edited_rubric.append(edited_item)
        total_weight += new_weight

    st.write(f"**Total weight: {total_weight}%** {'✅' if total_weight == 100 else '(will be auto-rebalanced to 100 on save)'}")

    if st.button("Save Rubric Changes"):
        with st.spinner("Saving..."):
            response = requests.put(
                f"{API_BASE_URL}/jobs/{job['id']}/rubric",
                json={"rubric": edited_rubric}
            )

        if response.status_code == 200:
            st.session_state.job = response.json()
            st.session_state.rubric_version += 1
            st.success("Rubric updated and rebalanced.")
            st.rerun()
        else:
            st.error(f"Failed to update rubric: {response.text}")
            
if st.session_state.job is not None:
    st.header("Step 3: Upload Resumes")

    uploaded_files = st.file_uploader(
        "Upload resume PDFs", type=["pdf"], accept_multiple_files=True
    )

    if uploaded_files and st.button("Score Resumes"):
        files_payload = [
            ("files", (f.name, f.getvalue(), "application/pdf"))
            for f in uploaded_files
        ]

        with st.spinner(f"Processing {len(uploaded_files)} resume(s)... this may take a while."):
            response = requests.post(
                f"{API_BASE_URL}/jobs/{st.session_state.job['id']}/resumes",
                files=files_payload
            )

        if response.status_code == 200:
            results = response.json()["results"]
            succeeded = [r for r in results if r["status"] == "success"]
            failed = [r for r in results if r["status"] == "failed"]

            st.success(f"Processed {len(results)} resume(s): {len(succeeded)} succeeded, {len(failed)} failed")

            if failed:
                with st.expander(f"{len(failed)} failed - click to see why"):
                    for r in failed:
                        st.write(f"**{r['filename']}**: {r['error']}")

            st.session_state.rankings_ready = True
        else:
            st.error(f"Upload failed: {response.text}")
            
    if st.session_state.get("rankings_ready"):
        st.header("Step 4: Rankings")

        rankings_response = requests.get(f"{API_BASE_URL}/jobs/{st.session_state.job['id']}/rankings")

        if rankings_response.status_code == 200:
            rankings = rankings_response.json()["rankings"]

            for i, entry in enumerate(rankings, start=1):
                with st.expander(f"#{i}. {entry['filename']} — {entry['total_score']}/10"):
                    st.write(entry["summary"])
                    st.write("**Criteria breakdown:**")
                    for c in entry["criteria_breakdown"]:
                        st.write(f"- **{c['criterion']}** ({c['score']}/10): {c['justification']}")