"""DriftGuard CLI Demo: Run all 3 scenarios and display formatted terminal summary."""

import json
from pathlib import Path
import pandas as pd

from driftguard.detector import load_contract, detect_drift
from driftguard.healer import propose_healing
from driftguard.pipeline import apply_adapter
from driftguard.models import DriftSeverity


def run_scenario(name: str, csv_path: Path, contract):
    print("\n" + "=" * 70)
    print(f"  RUNNING SCENARIO: {name}")
    print("=" * 70)
    
    df = pd.read_csv(csv_path)
    print(f"Ingested {len(df)} rows with columns: {list(df.columns)}")
    
    # Step 1: Detect
    report = detect_drift(df, contract)
    print(f"\n[Step 1] Initial Inspection:")
    print(f"  - Exact Matches: {report.exact_matches}")
    print(f"  - Missing Required: {report.missing_required}")
    print(f"  - Unexpected Columns: {report.unexpected_client_columns}")
    
    # Step 2: Heal
    report, adapter = propose_healing(df, contract, report)
    print(f"\n[Step 2] Auto-Healing Evaluation:")
    print(f"  - Severity Status: {report.severity.value}")
    print(f"  - Proposed Column Mappings: {adapter.column_mapping}")
    if adapter.clean_numeric_columns:
        print(f"  - Currency Sanitization Needed: {adapter.clean_numeric_columns}")
    if adapter.date_formats:
        print(f"  - Date Format Conversions: {adapter.date_formats}")
    if adapter.default_fillers:
        print(f"  - Default Backfills: {adapter.default_fillers}")
        
    # Step 3: Pipeline Execution
    if report.severity != DriftSeverity.BREAKING:
        clean_df = apply_adapter(df, adapter, contract)
        print(f"\n[Step 3] Ingestion Successful! Clean Output Schema:")
        print(clean_df.head(2).to_string(index=False))
    else:
        print(f"\n[Step 3] Ingestion Blocked: Critical schema violations require client consultation.")


def main():
    base_dir = Path(__file__).resolve().parent
    contract_path = base_dir / "data" / "baseline_contract.json"
    contract = load_contract(contract_path)
    
    run_scenario("1. Clean Feed (100% Match)", base_dir / "data" / "client_sample_good.csv", contract)
    run_scenario("2. Drifted Client Feed (Auto-Healed)", base_dir / "data" / "client_sample_drifted.csv", contract)
    run_scenario("3. Breaking Client Feed (Quarantined)", base_dir / "data" / "client_sample_breaking.csv", contract)
    
    print("\n" + "=" * 70)
    print("  ALL DEMO SCENARIOS COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()
