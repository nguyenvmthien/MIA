"""
Meeting AI Agent — Streamlit UI
Talks to the FastAPI backend at MEETING_AGENT_API_URL (default: http://localhost:8000).
"""

import json
import os
import time

import httpx
import streamlit as st

API_URL = os.getenv("MEETING_AGENT_API_URL", "http://localhost:8000")

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Meeting AI Agent",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🎙️ Meeting AI Agent")
    st.caption("Upload a meeting recording → get structured action items automatically.")
    st.divider()

    st.subheader("Links")
    st.markdown(
        f"- [API Docs]({API_URL}/docs)\n"
        f"- [Grafana](http://localhost:3000)\n"
        f"- [Prometheus](http://localhost:9090)"
    )
    st.divider()

    # Backend health indicator
    try:
        r = httpx.get(f"{API_URL}/health", timeout=3)
        if r.status_code == 200:
            st.success("Backend: online", icon="✅")
        else:
            st.warning(f"Backend: HTTP {r.status_code}", icon="⚠️")
    except Exception:
        st.error("Backend: unreachable", icon="🔴")

# ── Session state defaults ────────────────────────────────────────────────────

if "meeting_id" not in st.session_state:
    st.session_state["meeting_id"] = ""
if "poll_result" not in st.session_state:
    st.session_state["poll_result"] = None
if "polling" not in st.session_state:
    st.session_state["polling"] = False

# ── Main area ─────────────────────────────────────────────────────────────────

tab_upload, tab_results, tab_feedback = st.tabs(["📤 Upload", "📋 Results", "✏️ Feedback"])

# ── Tab 1: Upload ─────────────────────────────────────────────────────────────

with tab_upload:
    st.header("Submit a Meeting")

    # ── Non-blocking poll: if we're mid-poll, do one tick then rerun ──────────
    if st.session_state["polling"] and st.session_state["meeting_id"]:
        mid = st.session_state["meeting_id"]
        STAGE_HINTS = {
            "pending": ("Queued — waiting for a worker...", 5),
            "processing": ("Processing — STT + LLM extraction running...", 50),
            "completed": ("Done!", 100),
            "failed": ("Failed", 100),
        }
        st.info(f"Processing meeting `{mid}` …")
        progress_placeholder = st.empty()

        try:
            poll = httpx.get(f"{API_URL}/meetings/{mid}", timeout=10)
            poll.raise_for_status()
            poll_data = poll.json()
            job_status = poll_data.get("status", "pending")
            hint, pct = STAGE_HINTS.get(job_status, ("Running...", 60))
            progress_placeholder.progress(pct, text=f"{job_status.upper()} — {hint}")

            if job_status in ("completed", "failed"):
                st.session_state["poll_result"] = poll_data
                st.session_state["polling"] = False
                if job_status == "completed":
                    st.success("Done! Switch to the **📋 Results** tab.")
                else:
                    st.error(f"Processing failed: {poll_data.get('error', '?')}")
            else:
                time.sleep(4)
                st.rerun()
        except Exception as e:
            st.warning(f"Poll error: {e}")
            time.sleep(4)
            st.rerun()

        if st.button("Cancel polling"):
            st.session_state["polling"] = False
            st.rerun()

    else:
        col_left, col_right = st.columns([1, 1], gap="large")

        with col_left:
            st.subheader("Audio file")
            audio_file = st.file_uploader(
                "Upload meeting recording",
                type=["mp3", "wav", "m4a", "ogg", "mp4", "webm"],
                help="Supported: MP3, WAV, M4A, OGG, MP4, WebM",
            )
            if audio_file:
                st.audio(audio_file)

        with col_right:
            st.subheader("Participants")

            # ── Load worker database ──────────────────────────────────────────
            @st.cache_data(ttl=30)
            def _fetch_workers():
                try:
                    r = httpx.get(f"{API_URL}/workers", timeout=5)
                    r.raise_for_status()
                    return r.json().get("workers", [])
                except Exception:
                    return []

            all_workers = _fetch_workers()
            worker_by_id = {w["worker_id"]: w for w in all_workers}
            worker_options = {w["worker_id"]: f"{w['name']} ({w.get('role') or 'no role'})" for w in all_workers}

            selected_ids = st.multiselect(
                "Select meeting participants",
                options=list(worker_options.keys()),
                format_func=lambda wid: worker_options.get(wid, wid),
                placeholder="Choose participants…",
                help="Select from registered workers. Add new ones below if needed.",
            )

            # Show selected worker cards
            if selected_ids:
                for wid in selected_ids:
                    w = worker_by_id[wid]
                    aliases = ", ".join(w.get("aliases") or [])
                    st.caption(
                        f"✅ **{w['name']}** — {w.get('role') or '—'}"
                        + (f"  _(aka {aliases})_" if aliases else "")
                    )

            # ── Add new worker inline ─────────────────────────────────────────
            with st.expander("➕ Add a new participant to the database"):
                new_name = st.text_input("Full name *", key="new_worker_name", placeholder="e.g. Dave Lee")
                new_role = st.text_input("Role", key="new_worker_role", placeholder="e.g. Engineer")
                new_email = st.text_input("Email", key="new_worker_email", placeholder="dave@example.com")
                new_aliases_raw = st.text_input(
                    "Aliases (comma-separated)",
                    key="new_worker_aliases",
                    placeholder="Dave, D. Lee",
                )

                if st.button("Add participant", key="add_worker_btn"):
                    if not new_name.strip():
                        st.error("Name is required.")
                    else:
                        aliases_list = [a.strip() for a in new_aliases_raw.split(",") if a.strip()]
                        payload = {
                            "worker_id": "",
                            "name": new_name.strip(),
                            "role": new_role.strip() or None,
                            "email": new_email.strip() or None,
                            "aliases": aliases_list,
                            "skills": [],
                        }
                        try:
                            resp_w = httpx.post(f"{API_URL}/workers", json=payload, timeout=10)
                            if resp_w.status_code == 409:
                                st.warning(f"'{new_name}' already exists in the database.")
                            else:
                                resp_w.raise_for_status()
                                created = resp_w.json()
                                st.success(f"Added **{created['name']}** (ID: {created['worker_id']})")
                                st.cache_data.clear()
                                st.rerun()
                        except Exception as e:
                            st.error(f"Failed to add worker: {e}")

        # Build roster dict from selected workers
        roster_dict = {"workers": [worker_by_id[wid] for wid in selected_ids]}

        st.divider()
        submit_btn = st.button(
            "🚀 Submit Meeting", type="primary", disabled=audio_file is None
        )

        if submit_btn and audio_file:
            with st.spinner("Submitting to backend..."):
                try:
                    resp = httpx.post(
                        f"{API_URL}/meetings",
                        files={"audio": (audio_file.name, audio_file.getvalue(), audio_file.type)},
                        data={"roster_json": json.dumps(roster_dict)},
                        timeout=30,
                    )
                    resp.raise_for_status()
                except Exception as e:
                    st.error(f"Submission failed: {e}")
                    st.stop()

            result = resp.json()
            st.session_state["meeting_id"] = result["meeting_id"]
            st.session_state["poll_result"] = None
            st.session_state["polling"] = True
            st.rerun()

# ── Tab 2: Results ────────────────────────────────────────────────────────────

with tab_results:
    st.header("Meeting Results")

    meeting_id_input = st.text_input(
        "Meeting ID",
        value=st.session_state.get("meeting_id", ""),
        placeholder="Paste meeting_id here or submit from the Upload tab",
    )

    if st.button("🔍 Load Results") and meeting_id_input:
        try:
            r = httpx.get(f"{API_URL}/meetings/{meeting_id_input}", timeout=15)
            r.raise_for_status()
            st.session_state["poll_result"] = r.json()
            st.session_state["meeting_id"] = meeting_id_input
        except Exception as e:
            st.error(f"Failed to fetch: {e}")

    data = st.session_state.get("poll_result")

    if not data:
        st.info("No results loaded yet. Submit a meeting or enter a meeting ID above.")
    else:
        job_status = data.get("status", data.get("job_status", "unknown"))

        if job_status == "failed":
            st.error(f"Processing failed: {data.get('error', 'unknown error')}")
        elif job_status in ("pending", "processing"):
            st.warning(f"Job is still **{job_status}**. Refresh in a moment.")
        else:
            with st.expander("📝 Meeting Summary", expanded=True):
                st.write(data.get("summary_text", "No summary available."))
                participants = data.get("participants", [])
                if participants:
                    st.markdown(
                        "**Participants:** " + "  ".join(f"`{p}`" for p in participants)
                    )

            action_items = data.get("action_items", [])
            human_review = data.get("human_review_items", [])
            unresolved = data.get("unresolved_items", [])

            inner_tab_a, inner_tab_b, inner_tab_c = st.tabs([
                f"✅ Action Items ({len(action_items)})",
                f"👁️ Human Review ({len(human_review)})",
                f"❓ Unresolved ({len(unresolved)})",
            ])

            def _render_tasks(tasks: list) -> None:
                if not tasks:
                    st.info("None")
                    return
                for task in tasks:
                    priority = task.get("priority", "medium")
                    priority_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                        priority, "⚪"
                    )
                    conf = task.get("extraction_confidence", 0)
                    with st.container(border=True):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"**{task.get('description', '—')}**")
                            st.caption(
                                f"👤 {task.get('assignee', '—')}  |  "
                                f"📅 {task.get('due_date', '—')}  |  "
                                f"{priority_color} {priority.capitalize()}"
                            )
                        with col2:
                            st.metric("Confidence", f"{conf:.0%}")

            with inner_tab_a:
                _render_tasks(action_items)
            with inner_tab_b:
                _render_tasks(human_review)
            with inner_tab_c:
                _render_tasks(unresolved)

            metrics = data.get("run_metrics", {})
            if metrics:
                st.subheader("Run Metrics")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Tasks extracted", metrics.get("tasks_extracted", 0))
                m2.metric("LLM tokens used", metrics.get("total_tokens_used", 0))
                m3.metric("Hallucination flags", metrics.get("hallucination_flags", 0))
                m4.metric("Schema failures", metrics.get("schema_validation_failures", 0))

                timings = metrics.get("stage_timings", {})
                if timings:
                    t1, t2, t3 = st.columns(3)
                    t1.metric("STT time", f"{timings.get('stt_ms', 0) / 1000:.1f}s")
                    t2.metric("LLM time", f"{timings.get('llm_ms', 0) / 1000:.1f}s")
                    t3.metric("Total time", f"{sum(timings.values()) / 1000:.1f}s")

# ── Tab 3: Feedback ───────────────────────────────────────────────────────────

with tab_feedback:
    st.header("Submit Corrections")
    st.caption("Corrections are stored and used to improve the extraction model over time.")

    data = st.session_state.get("poll_result")
    action_items = data.get("action_items", []) if data else []
    mid = st.session_state.get("meeting_id", "")

    if not action_items:
        st.info("Load a completed meeting in the Results tab first.")
    else:
        reviewer = st.text_input("Your name (reviewer)", placeholder="e.g. Alice Chen")

        corrections = []
        for task in action_items:
            task_id = task["task_id"]
            orig_desc = task.get("description", "")
            orig_assignee = task.get("assignee", "") or ""

            with st.expander(f"Task: {orig_desc or task_id}", expanded=False):
                col_a, col_b = st.columns(2)
                with col_a:
                    corrected_desc = st.text_input(
                        "Corrected description",
                        value=orig_desc,
                        key=f"desc_{task_id}",
                    )
                    corrected_assignee = st.text_input(
                        "Corrected assignee",
                        value=orig_assignee,
                        key=f"assignee_{task_id}",
                    )
                with col_b:
                    corrected_due = st.text_input(
                        "Corrected due date (YYYY-MM-DD)",
                        value=task.get("due_date", "") or "",
                        key=f"due_{task_id}",
                    )
                    is_fp = st.checkbox("False positive (should not have been extracted)", key=f"fp_{task_id}")

                corrections.append({
                    "meeting_id": mid,
                    "task_id": task_id,
                    "original_description": orig_desc,
                    "corrected_description": corrected_desc if corrected_desc != orig_desc else None,
                    "original_assignee": orig_assignee,
                    "corrected_assignee": corrected_assignee if corrected_assignee != orig_assignee else None,
                    "original_due_date": task.get("due_date"),
                    "corrected_due_date": corrected_due or None,
                    "is_false_positive": is_fp,
                })

        if st.button("💾 Submit Feedback", type="primary"):
            if not mid:
                st.error("No meeting ID found. Load results first.")
            else:
                payload = {
                    "reviewer": reviewer or "anonymous",
                    "corrections": corrections,
                }
                try:
                    r = httpx.post(
                        f"{API_URL}/meetings/{mid}/feedback",
                        json=payload,
                        timeout=15,
                    )
                    r.raise_for_status()
                    result = r.json()
                    st.success(
                        f"Saved {result.get('corrections_saved', 0)} correction(s). Thank you!"
                    )
                except Exception as e:
                    st.error(f"Failed to submit: {e}")
