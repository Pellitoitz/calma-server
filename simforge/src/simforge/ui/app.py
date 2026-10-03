"""SimForge local UI. Run with:  simforge ui   (or: streamlit run src/simforge/ui/app.py)"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from simforge.services.app import SimForgeApp
from simforge.ui import calendar_view, data_view, economics_view, maintenance_view, products_view, scenarios_view, views

st.set_page_config(page_title="SimForge", page_icon="🏭", layout="wide")


@st.cache_resource
def get_app(workspace: str, library: str) -> SimForgeApp:
    """Cached per (workspace, library): changing SIMFORGE_WORKSPACE never reuses another workspace."""
    try:
        from dotenv import load_dotenv  # optional
        load_dotenv()
    except ImportError:
        pass
    _load_env_file()
    return SimForgeApp()


def _load_env_file() -> None:
    import os
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


_load_env_file()
app = get_app(os.environ.get("SIMFORGE_WORKSPACE", "./workspace"), os.environ.get("SIMFORGE_LIBRARY", ""))

# ------------------------------------------------------------------ sidebar: projects
with st.sidebar:
    st.title("🏭 SimForge")
    st.caption("The AI builds · the engine computes · the system checks · the engineer validates")
    projects = app.list_projects()
    slugs = [p.slug for p in projects]
    cur = st.session_state.get("project")
    if slugs:
        sel = st.selectbox("Project", slugs, index=slugs.index(cur) if cur in slugs else 0,
                           format_func=lambda s: next(p.name for p in projects if p.slug == s))
        st.session_state["project"] = sel
    with st.expander("New project", expanded=not slugs):
        name = st.text_input("Name")
        if st.button("Create", disabled=not name):
            p = app.create_project(name)
            st.session_state["project"] = p.meta.slug
            st.rerun()
    with st.expander("Import / export"):
        up = st.file_uploader("Import .simproject", type=["simproject", "zip"])
        if up and st.button("Import"):
            with tempfile.NamedTemporaryFile(suffix=".simproject", delete=False) as fh:
                fh.write(up.getvalue())
            p = app.workspace.import_project(Path(fh.name))
            st.session_state["project"] = p.meta.slug
            st.rerun()
        if st.session_state.get("project"):
            tmp = Path(tempfile.gettempdir()) / f"{st.session_state['project']}.simproject"
            app.workspace.export_project(st.session_state["project"], tmp)
            st.download_button("Export project (.simproject)", tmp.read_bytes(), file_name=tmp.name)
    st.caption(f"Workspace (client data): `{app.workspace.root}`")
    st.caption(f"User library: `{app.library_dir}`")
    st.caption("LLM: " + (f"{app.provider.name} / {app.provider.model}" if app.provider else "none — offline rule-based interpreter"))

slug = st.session_state.get("project")
if not slug:
    st.header("Welcome")
    st.write("Create a project in the sidebar, then describe your process in the **Assistant** tab.")
    st.stop()

project = app.open_project(slug)
st.header(project.name)
_cur = project.current_model()
if _cur is not None:  # where am I: version, approval, MISSING, engine, validation status (1.0 release audit)
    from simforge import ENGINE_VERSION as _EV
    from simforge import __version__ as _PV
    _missing = sum(1 for m in _cur.missing if m.required)
    st.caption(f"Model v{project.meta.current_version} · `{_cur.content_hash()}` · engineer approval: "
               f"**{'YES' if _cur.is_approved else 'NO'}** · required MISSING values: **{_missing}** · SimForge {_PV} · engine {_EV} · "
               "validation: capabilities SYNTHETICALLY_VALIDATED (tests), real-data validation per capability only "
               "(economics: NOT_EXECUTED) — see docs/release/1.0_capability_matrix.md")
if app.provider:
    st.warning(f"Remote LLM active ({app.provider.name}): text typed in the Assistant tab is SENT to the provider. "
               "Unset ANTHROPIC_API_KEY to work fully offline.")
tabs = st.tabs(["Assistant", "Model", "Data", "Calendars", "Products", "Maintenance", "Run & results", "Economics",
                "Experiments", "Library", "Report", "Project"])
with tabs[0]:
    views.assistant_tab(app, project)
with tabs[1]:
    views.model_tab(app, project)
with tabs[2]:
    data_view.data_tab(app, project)
with tabs[3]:
    calendar_view.calendar_tab(app, project)
with tabs[4]:
    products_view.products_tab(app, project)
with tabs[5]:
    maintenance_view.maintenance_tab(app, project)
with tabs[6]:
    views.run_tab(app, project)
with tabs[7]:
    economics_view.economics_tab(app, project)
with tabs[8]:
    views.experiments_tab(app, project)
with tabs[9]:
    views.library_tab(app)
with tabs[10]:
    views.report_tab(app, project)
with tabs[11]:
    st.markdown("### Scenarios & run comparison")
    scenarios_view.scenarios_tab(app, project)
    st.divider()
    views.project_tab(app, project)
