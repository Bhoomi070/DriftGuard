import re
import pandas as pd
from driftguard.models import AdapterRule, DataContract


def apply_adapter(df: pd.DataFrame, adapter: AdapterRule, contract: DataContract) -> pd.DataFrame:
    """Transforms a drifted client DataFrame into a strictly contract-compliant DataFrame."""
    out = df.copy()

    # 1. Strip currency and non-numeric characters for flagged columns
    for col in adapter.clean_numeric_columns:
        if col in out.columns:
            out[col] = (
                out[col]
                .astype(str)
                .apply(lambda x: re.sub(r"[$,€£\s]", "", x).replace(",", ""))
            )
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # 2. Standardize dates to YYYY-MM-DD
    for col, fmt in adapter.date_formats.items():
        if col in out.columns:
            # Parse using specified format, output as YYYY-MM-DD string
            parsed = pd.to_datetime(out[col], format=fmt, errors="coerce")
            out[col] = parsed.dt.strftime("%Y-%m-%d")

    # 3. Rename columns based on mapping
    out = out.rename(columns=adapter.column_mapping)

    # 4. Fill default values for missing optional fields
    for target_col, def_val in adapter.default_fillers.items():
        if target_col not in out.columns:
            out[target_col] = def_val

    # 5. Filter & Order to contract fields only
    contract_col_names = [f.name for f in contract.fields]
    available_cols = [c for c in contract_col_names if c in out.columns]
    out = out[available_cols]

    # 6. Type coercion based on contract definition
    for f in contract.fields:
        if f.name in out.columns:
            if f.data_type == "float":
                out[f.name] = pd.to_numeric(out[f.name], errors="coerce")
            elif f.data_type == "int":
                out[f.name] = pd.to_numeric(out[f.name], errors="coerce").astype("Int64")
            elif f.data_type == "string":
                out[f.name] = out[f.name].astype(str)

    return out
