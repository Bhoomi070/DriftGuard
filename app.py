import json
from pathlib import Path
import pandas as pd
import streamlit as st

from driftguard.detector import load_contract, detect_drift
from driftguard.healer import propose_healing
from driftguard.pipeline import apply_adapter
from driftguard.models import DriftSeverity, DriftType, AdapterRule

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="DriftGuard | FDE Ingestion Platform",
    page_icon="🛡️",
    layout="wide"
)

# Paths
BASE_DIR = Path(__file__).resolve().parent
CONTRACT_PATH = BASE_DIR / "data" / "baseline_contract.json"
SAMPLES = {
    "Sample 1: Clean Feed (100% Compliant)": BASE_DIR / "data" / "client_sample_good.csv",
    "Sample 2: Drifted Client Feed (Auto-Healable)": BASE_DIR / "data" / "client_sample_drifted.csv",
    "Sample 3: Breaking Client Feed (Fatal Violations)": BASE_DIR / "data" / "client_sample_breaking.csv"
}

# --- HEADER ---
st.title("🛡️ DriftGuard")
st.caption("Forward Deployed Engineering (FDE) Platform: Schema Drift Detection, Auto-Healing & Human-in-the-Loop Triage")

# Load Contract
contract = load_contract(CONTRACT_PATH)

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Ingestion Settings")
    st.subheader("Target Data Contract")
    st.info(f"**Contract:** {contract.name}\n\n**Version:** {contract.version}")
    
    with st.expander("View Expected Schema Fields"):
        for f in contract.fields:
            req_str = "*(Required)*" if f.required else "*(Optional)*"
            st.markdown(f"- **`{f.name}`** `{f.data_type}` {req_str}")

    st.divider()
    st.subheader("Select Client Data Feed")
    feed_choice = st.radio("Input Source:", ["Preset Sample", "Upload CSV"])
    
    selected_file = None
    if feed_choice == "Preset Sample":
        sample_name = st.selectbox("Choose a scenario:", list(SAMPLES.keys()), index=1)
        selected_file = SAMPLES[sample_name]
    else:
        uploaded = st.file_uploader("Upload client CSV file", type=["csv"])
        if uploaded:
            selected_file = uploaded

# --- MAIN LOGIC ---
if selected_file:
    # Read CSV
    df = pd.read_csv(selected_file)
    
    with st.expander("📄 Raw Client Data Preview", expanded=False):
        st.dataframe(df, use_container_width=True)

    # 1. Run Drift Detection & Healing Proposals
    initial_report = detect_drift(df, contract)
    healed_report, base_adapter = propose_healing(df, contract, initial_report)

    # Status Banner
    st.divider()
    col_status, col_kpi1, col_kpi2, col_kpi3 = st.columns([2, 1, 1, 1])

    with col_status:
        if healed_report.severity == DriftSeverity.CLEAN:
            st.success("### Status: 🟢 CLEAN\nData matches target contract perfectly.")
        elif healed_report.severity == DriftSeverity.HEALABLE:
            st.warning("### Status: 🟡 HEALABLE DRIFT\nBreaking schema changes detected. Auto-remapping plan prepared.")
        else:
            st.error("### Status: 🔴 BREAKING DRIFT\nFatal missing fields. Pipeline requires client engineering review.")

    with col_kpi1:
        st.metric("Contract Fields", healed_report.total_contract_fields)
    with col_kpi2:
        st.metric("Exact Matches", len(healed_report.exact_matches))
    with col_kpi3:
        st.metric("Missing Required", len(healed_report.missing_required))

    # Diagnostics Logs
    if healed_report.diagnostics:
        with st.expander("🔍 Ingestion Diagnostics & Alerts", expanded=(healed_report.severity != DriftSeverity.CLEAN)):
            for d in healed_report.diagnostics:
                st.write(f"- {d}")

    # 2. Schema Translation & Diff Table
    st.subheader("🧩 Schema Reconciliation & Mapping Plan")
    
    table_rows = []
    for p in healed_report.proposals:
        conf_pct = f"{int(p.confidence * 100)}%" if p.confidence > 0 else "0%"
        table_rows.append({
            "Client Column": p.client_column,
            "Target Contract Field": p.target_column or "<DROPPED>",
            "Confidence": conf_pct,
            "Match Method": p.match_method,
            "Drift Type": p.drift_type.value,
            "Reasoning": p.reasoning
        })

    mapping_df = pd.DataFrame(table_rows)
    st.dataframe(mapping_df, use_container_width=True)

    # 3. Human-In-The-Loop Execution
    st.divider()
    st.subheader("🚀 Human-in-the-Loop (HITL) Execution")

    if healed_report.severity == DriftSeverity.BREAKING:
        st.error("⛔ Cannot auto-execute pipeline: One or more required fields could not be mapped. Please request schema clarification from client.")
    else:
        st.info("💡 You can review or override the auto-generated adapter before applying it to the pipeline.")
        
        # Display the Adapter JSON preview
        with st.expander("🛠️ View Inferred Adapter Rule (JSON)"):
            st.json(base_adapter.model_dump())

        if st.button("Apply Adapter & Ingest Data", type="primary"):
            cleaned_df = apply_adapter(df, base_adapter, contract)
            
            st.success("✅ Data successfully sanitized, normalized, and ingested!")
            st.dataframe(cleaned_df, use_container_width=True)

            # Export options
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.download_button(
                    label="📥 Download Sanitized CSV",
                    data=cleaned_df.to_csv(index=False),
                    file_name="sanitized_client_feed.csv",
                    mime="text/csv"
                )
            with col_d2:
                st.download_button(
                    label="💾 Download Reusable Adapter Rule (JSON)",
                    data=json.dumps(base_adapter.model_dump(), indent=2),
                    file_name="driftguard_adapter.json",
                    mime="application/json"
                )
else:
    st.warning("Please select or upload a client CSV feed to begin.")
