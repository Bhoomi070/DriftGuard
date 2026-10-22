from pathlib import Path
import pandas as pd
import pytest

from driftguard.detector import load_contract, detect_drift
from driftguard.healer import propose_healing
from driftguard.pipeline import apply_adapter
from driftguard.models import DriftSeverity, DriftType

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = PROJECT_ROOT / "data" / "baseline_contract.json"
GOOD_CSV = PROJECT_ROOT / "data" / "client_sample_good.csv"
DRIFTED_CSV = PROJECT_ROOT / "data" / "client_sample_drifted.csv"
BREAKING_CSV = PROJECT_ROOT / "data" / "client_sample_breaking.csv"


@pytest.fixture
def contract():
    return load_contract(CONTRACT_PATH)


def test_clean_data(contract):
    df = pd.read_csv(GOOD_CSV)
    report = detect_drift(df, contract)
    assert report.severity == DriftSeverity.CLEAN
    assert len(report.missing_required) == 0
    assert len(report.unexpected_client_columns) == 0

    report, adapter = propose_healing(df, contract, report)
    assert report.severity == DriftSeverity.CLEAN


def test_drifted_data_healing(contract):
    df = pd.read_csv(DRIFTED_CSV)
    
    # Initial detection should identify missing fields & unexpected columns
    report = detect_drift(df, contract)
    assert report.severity in [DriftSeverity.HEALABLE, DriftSeverity.BREAKING]
    assert len(report.missing_required) > 0
    
    # Healing should propose valid mappings for all required fields
    report, adapter = propose_healing(df, contract, report)
    assert report.severity == DriftSeverity.HEALABLE

    # Check key mappings
    mapping = adapter.column_mapping
    assert mapping.get("cust_id") == "customer_id"
    assert mapping.get("client_name") == "full_name"
    assert mapping.get("email_address") == "email"
    assert mapping.get("registered_on") == "signup_date"
    assert mapping.get("balance_usd") == "account_balance"
    assert mapping.get("membership_level") == "tier"
    assert adapter.default_fillers.get("status") == "active"

    # Execute pipeline
    clean_df = apply_adapter(df, adapter, contract)
    
    # Verify resulting DataFrame matches contract specification
    assert "customer_id" in clean_df.columns
    assert "account_balance" in clean_df.columns
    assert clean_df["account_balance"].dtype == float
    assert clean_df["status"].iloc[0] == "active"
    # Check date was converted to YYYY-MM-DD
    assert clean_df["signup_date"].iloc[0] == "2025-04-14"


def test_breaking_data_flagged(contract):
    df = pd.read_csv(BREAKING_CSV)
    report = detect_drift(df, contract)
    report, adapter = propose_healing(df, contract, report)
    
    # Missing email and customer ID should cause healing to fail -> BREAKING
    assert report.severity == DriftSeverity.BREAKING
    missing_targets = [p.target_column for p in report.proposals if p.drift_type == DriftType.MISSING_REQUIRED]
    assert "email" in missing_targets
