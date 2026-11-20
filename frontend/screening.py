"""Screen the current selection and retain per-file progress in the browser session."""
import hashlib
import json
import math
import time

import streamlit as st

from api_client import screen_resume
from components import display_text, nav_button


FILE_ERRORS = {"invalid_pdf", "input_too_long", "input_too_large"}


def pending_or_previous(selected, history):
    return [
        history.get(key, {"filename": upload.name, "status": "pending"})
        for key, upload in selected.items()
    ]


def show_results(results):
    successes = sum(item["status"] == "success" for item in results)
    failures = [item for item in results if item["status"] == "failed"]
    pending = sum(item["status"] == "pending" for item in results)
    limited = sum(item.get("error_code") == "rate_limited" for item in failures)
    if pending or limited:
        st.warning(f"{successes} succeeded · {limited} waiting for AI capacity · "
                   f"{pending} awaiting submission · {len(failures) - limited} failed.")
    elif failures:
        st.warning(f"Evaluation finished: {successes} succeeded and {len(failures)} failed.")
    else:
        st.success(f"Evaluation finished: {successes} succeeded and 0 failed.")
    if failures:
        with st.expander("Review processing errors", expanded=True):
            for item in failures:
                st.text(item["filename"])
                error = item.get("error")
                st.caption(display_text(error) if isinstance(error, str) and 0 < len(error) <= 200
                           else "Could not process this resume.")
    nav_button("View Candidate Rankings →", "Candidate Rankings", key="upload_next", primary=True)


def render_screening(job, unsaved_changes, refresh_rankings):
    state = st.session_state
    scope = (job["id"], json.dumps(job["rubric"], sort_keys=True))
    if state.get("screening_scope") != scope:
        state.previous_batch = state.eval_result if state.get("screening_scope") is None else None
        state.screening_scope = scope
        state.screening_history = {}
        state.eval_result = None
    history = state.screening_history
    with st.container(border=True):
        st.subheader("Upload Candidate Resumes")
        st.caption("Select your PDFs together. Shortlist screens them one at a time against your saved criteria.")
        previous_names = set()
        if state.get("previous_batch"):
            older_results = state.previous_batch
            failed_names = [item["filename"] for item in older_results if item["status"] == "failed"]
            previous_names = {item["filename"] for item in older_results if item["status"] == "success"} - set(failed_names)
            if failed_names:
                saved_count = sum(item["status"] == "success" for item in older_results)
                st.info(f"Earlier evaluation · {saved_count} scored · {len(failed_names)} failed. "
                        "Select only the failed files listed below to continue with this job.")
                for name in failed_names:
                    st.text(name)
        uploaded = st.file_uploader("Candidate resumes (PDF only)", type=["pdf"], accept_multiple_files=True,
                                    key=f"uploads_{job['id']}")
        selected = {(file.name, hashlib.sha256(file.getbuffer()).digest()): file for file in uploaded}
        if selected:
            st.write(f"{len(selected)} distinct PDF(s) selected")
            for file in selected.values():
                st.text(f"{file.name}  ·  {file.size / 1024:.1f} KB")
        eligible = []
        uncertain = []
        for key in selected:
            previous = history.get(key, {})
            code = previous.get("error_code")
            if previous.get("status") == "success" or code in FILE_ERRORS:
                continue
            if code == "unconfirmed" and not previous.get("resume_id"):
                uncertain.append(key)
            else:
                eligible.append(key)
        has_history = any(key in history for key in selected)
        seconds_left = math.ceil(state.get("screening_retry_at", 0) - time.time())
        if seconds_left > 0:
            minutes, seconds = divmod(seconds_left, 60)
            st.info(f"The AI service requested a pause. Try Continue screening after {minutes} min {seconds} sec.")
        elif any(history.get(key, {}).get("error_code") == "rate_limited" for key in selected):
            st.info("Use Continue screening to retry the waiting PDFs. Files already scored with these criteria are skipped.")
        label = "Continue screening" if has_history else "Evaluate Candidates"
        includes_older_scores = bool(previous_names.intersection(key[0] for key in selected))
        if includes_older_scores:
            st.warning("Remove the previously scored PDFs from this selection before continuing.")
        run = st.button(f"{label} ({len(eligible)})", type="primary",
                        disabled=not eligible or unsaved_changes or includes_older_scores)
        if any(history.get(key, {}).get("error_code") in FILE_ERRORS for key in selected):
            st.info("Replace the PDFs with file errors, then select their corrected versions to continue.")
        if uncertain:
            st.warning("The service may already have saved a score for the unconfirmed uploads. Check Candidate Rankings before submitting them again.")
            if st.button(f"Retry unconfirmed uploads ({len(uncertain)})", disabled=unsaved_changes):
                eligible = uncertain
                run = True
        if run:
            if seconds_left > 0:
                st.caption("The remaining PDFs are still queued.")
            else:
                state.previous_batch = None
                progress = st.progress(0.0)
                for index, key in enumerate(eligible):
                    upload = selected[key]
                    progress.progress(index / len(eligible), text=f"Screening PDF {index + 1} of {len(eligible)}. Please keep this page open.")
                    previous_id = history.get(key, {}).get("resume_id")
                    resume_id = previous_id if type(previous_id) is int and previous_id > 0 else None
                    result = screen_resume(job["id"], upload, resume_id)
                    history[key] = result
                    state.eval_result = pending_or_previous(selected, history)
                    if result.get("error_code") == "rate_limited":
                        delay = result.get("retry_after_seconds")
                        if type(delay) in (int, float) and math.isfinite(delay) and delay > 0:
                            state.screening_retry_at = time.time() + delay
                        break
                progress.empty()
                error = refresh_rankings(job["id"])
                if error:
                    st.warning("Rankings could not be refreshed. " + display_text(error))
                # Rebuild the controls using the results so another click only submits remaining work.
                if not error:
                    st.rerun()
    if selected and any(key in history for key in selected):
        state.eval_result = pending_or_previous(selected, history)
        show_results(state.eval_result)
    elif not selected and state.eval_result:
        show_results(state.eval_result)
