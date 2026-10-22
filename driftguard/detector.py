import json
from pathlib import Path
from typing import Union
import pandas as pd
from driftguard.models import DataContract, DriftReport, DriftSeverity, DriftType


def load_contract(contract_source: Union[str, Path, dict]) -> DataContract:
    """Load and parse DataContract from file path or dictionary."""
    if isinstance(contract_source, (str, Path)):
        with open(contract_source, "r", encoding="utf-8") as f:
            data = json.load(f)
        return DataContract(**data)
    elif isinstance(contract_source, dict):
        return DataContract(**contract_source)
    else:
        raise ValueError("contract_source must be a file path or dict")


def detect_drift(df: pd.DataFrame, contract: DataContract) -> DriftReport:
    """Inspects a client DataFrame against expected DataContract."""
    client_cols = [str(c).strip() for c in df.columns]
    contract_fields = {f.name: f for f in contract.fields}
    contract_field_names = set(contract_fields.keys())

    exact_matches = [c for c in client_cols if c in contract_field_names]
    unexpected_cols = [c for c in client_cols if c not in contract_field_names]
    
    missing_fields = [name for name in contract_field_names if name not in client_cols]
    missing_required = [name for name in missing_fields if contract_fields[name].required]
    missing_optional = [name for name in missing_fields if not contract_fields[name].required]

    diagnostics = []

    # Check for empty dataframe
    if df.empty:
        diagnostics.append("DataFrame is completely empty (0 rows).")
        return DriftReport(
            contract_name=contract.name,
            contract_version=contract.version,
            severity=DriftSeverity.BREAKING,
            total_contract_fields=len(contract.fields),
            exact_matches=exact_matches,
            missing_required=missing_required,
            missing_optional=missing_optional,
            unexpected_client_columns=unexpected_cols,
            diagnostics=diagnostics
        )

    # Inspect unexpected columns for formatting quirks (currency, date strings)
    for col in unexpected_cols:
        sample_vals = df[col].dropna().astype(str).head(5).tolist()
        # Check if values look like currency
        if any("$" in v or "€" in v for v in sample_vals):
            diagnostics.append(f"Column '{col}' appears to contain formatted currency strings.")
        # Check if values look like DD-MM-YYYY dates
        if any("-" in v and len(v.split("-")[0]) == 2 for v in sample_vals):
            diagnostics.append(f"Column '{col}' appears to use non-standard date format (e.g. DD-MM-YYYY).")

    # Determine Severity
    if not missing_required and not unexpected_cols:
        severity = DriftSeverity.CLEAN
        diagnostics.append("All contract fields present and matched exactly.")
    elif missing_required:
        # If we have unexpected columns available, it might be healable via renaming
        if len(unexpected_cols) >= len(missing_required):
            severity = DriftSeverity.HEALABLE
            diagnostics.append(f"Found {len(missing_required)} missing required field(s) with {len(unexpected_cols)} candidate client column(s).")
        else:
            severity = DriftSeverity.BREAKING
            diagnostics.append(f"Critical: {len(missing_required)} required fields missing with insufficient client columns.")
    else:
        # No missing required, but extra/unexpected columns or missing optionals
        severity = DriftSeverity.HEALABLE
        diagnostics.append(f"All required fields present, but observed {len(unexpected_cols)} unexpected columns.")

    return DriftReport(
        contract_name=contract.name,
        contract_version=contract.version,
        severity=severity,
        total_contract_fields=len(contract.fields),
        exact_matches=exact_matches,
        missing_required=missing_required,
        missing_optional=missing_optional,
        unexpected_client_columns=unexpected_cols,
        diagnostics=diagnostics
    )
