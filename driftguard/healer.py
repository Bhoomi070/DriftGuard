import re
from typing import Tuple, Dict, List
import pandas as pd
from rapidfuzz import fuzz
from driftguard.models import (
    DataContract,
    DriftReport,
    DriftSeverity,
    DriftType,
    FieldMatchProposal,
    AdapterRule
)


def _detect_date_format(samples: List[str]) -> str:
    """Heuristic check for common client date string patterns."""
    for s in samples:
        s = s.strip()
        # DD-MM-YYYY or DD/MM/YYYY
        if re.match(r"^\d{2}[-/]\d{2}[-/]\d{4}$", s):
            sep = "/" if "/" in s else "-"
            # Check if first part > 12 -> definitely day first
            parts = s.split(sep)
            if int(parts[0]) > 12:
                return f"%d{sep}%m{sep}%Y"
            # Default to day-first if standard European/international client
            return f"%d{sep}%m{sep}%Y"
        # YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return "%Y-%m-%d"
    return "%Y-%m-%d"


def _is_probable_email(samples: List[str]) -> bool:
    count = sum(1 for s in samples if "@" in s and "." in s)
    return count >= max(1, len(samples) // 2)


def _is_probable_currency_or_number(samples: List[str]) -> bool:
    count = 0
    for s in samples:
        clean = re.sub(r"[$,€£\s]", "", s).replace(",", "")
        try:
            float(clean)
            count += 1
        except ValueError:
            pass
    return count >= max(1, len(samples) // 2)


def propose_healing(df: pd.DataFrame, contract: DataContract, report: DriftReport) -> Tuple[DriftReport, AdapterRule]:
    """Generates schema translation proposals and a concrete AdapterRule."""
    contract_fields = {f.name: f for f in contract.fields}
    missing_all = report.missing_required + report.missing_optional
    available_client_cols = list(report.unexpected_client_columns)

    proposals: List[FieldMatchProposal] = []
    col_mapping: Dict[str, str] = {}
    clean_numeric: List[str] = []
    date_formats: Dict[str, str] = {}
    default_fillers: Dict[str, Any] = {}

    # Exact matches are already 1:1 mapped
    for exact_col in report.exact_matches:
        proposals.append(
            FieldMatchProposal(
                client_column=exact_col,
                target_column=exact_col,
                confidence=1.0,
                match_method="exact",
                drift_type=DriftType.EXACT_MATCH,
                sample_values=df[exact_col].dropna().astype(str).head(3).tolist(),
                reasoning="Exact column name match found in contract."
            )
        )

    # For each missing contract field, find the best matching client column
    for target_name in missing_all:
        field_cfg = contract_fields[target_name]
        best_candidate = None
        highest_score = 0.0
        match_method = "none"
        reasoning = ""

        for client_col in available_client_cols:
            score = 0.0
            norm_client = client_col.lower().replace("_", "").replace("-", "")
            norm_target = target_name.lower().replace("_", "").replace("-", "")

            # 1. Synonym Match (Highest Confidence)
            if client_col.lower() in [s.lower() for s in field_cfg.synonyms]:
                score = 0.98
                match_method = "synonym"
                reasoning = f"Matched known alias '{client_col}' defined in contract synonyms."
            
            # 2. Fuzzy String Match
            else:
                fuzzy_ratio = fuzz.token_sort_ratio(client_col.lower(), target_name.lower()) / 100.0
                if fuzzy_ratio > 0.65 and fuzzy_ratio > score:
                    score = fuzzy_ratio
                    match_method = "fuzzy_name"
                    reasoning = f"Lexical similarity score {score:.2f} with '{target_name}'."

            # 3. Content Profiling Boost / Verification
            samples = df[client_col].dropna().astype(str).head(10).tolist()
            if samples:
                if field_cfg.data_type == "string" and "email" in target_name and _is_probable_email(samples):
                    score = max(score, 0.95)
                    match_method = "content_profiling"
                    reasoning += " Verified email pattern (@, domain) in sample rows."
                elif field_cfg.data_type == "float" and _is_probable_currency_or_number(samples):
                    if any("$" in s or "," in s for s in samples):
                        score = max(score, 0.85)
                        reasoning += " Contains parseable currency/numeric values."
                elif field_cfg.data_type == "date":
                    fmt = _detect_date_format(samples)
                    score = max(score, 0.82)
                    reasoning += f" Detected date structure (inferred {fmt})."

            if score > highest_score:
                highest_score = score
                best_candidate = client_col

        # If a viable candidate was found (confidence threshold >= 0.60)
        if best_candidate and highest_score >= 0.60:
            available_client_cols.remove(best_candidate)
            col_mapping[best_candidate] = target_name

            sample_vals = df[best_candidate].dropna().astype(str).head(3).tolist()

            # Check if this column needs special numeric or date handling
            if field_cfg.data_type == "float" and any("$" in v or "," in v for v in sample_vals):
                clean_numeric.append(best_candidate)

            if field_cfg.data_type == "date":
                detected_fmt = _detect_date_format(df[best_candidate].dropna().astype(str).head(10).tolist())
                date_formats[best_candidate] = detected_fmt

            proposals.append(
                FieldMatchProposal(
                    client_column=best_candidate,
                    target_column=target_name,
                    confidence=round(highest_score, 2),
                    match_method=match_method,
                    drift_type=DriftType.RENAMED_COLUMN,
                    sample_values=sample_vals,
                    reasoning=reasoning.strip()
                )
            )
        else:
            # No viable candidate found
            if field_cfg.required:
                proposals.append(
                    FieldMatchProposal(
                        client_column="<NONE>",
                        target_column=target_name,
                        confidence=0.0,
                        match_method="failed",
                        drift_type=DriftType.MISSING_REQUIRED,
                        reasoning=f"Required contract field '{target_name}' could not be matched with any client column."
                    )
                )
            else:
                # Optional field missing: apply default if defined
                if field_cfg.default is not None:
                    default_fillers[target_name] = field_cfg.default
                proposals.append(
                    FieldMatchProposal(
                        client_column="<NONE>",
                        target_column=target_name,
                        confidence=1.0,
                        match_method="default_fallback",
                        drift_type=DriftType.MISSING_OPTIONAL,
                        reasoning=f"Optional field missing. Ingestion will backfill default: '{field_cfg.default}'."
                    )
                )

    # Any remaining client columns that were never mapped
    for unmapped_col in available_client_cols:
        proposals.append(
            FieldMatchProposal(
                client_column=unmapped_col,
                target_column=None,
                confidence=0.0,
                match_method="unmapped",
                drift_type=DriftType.UNEXPECTED_COLUMN,
                sample_values=df[unmapped_col].dropna().astype(str).head(3).tolist(),
                reasoning="Column exists in client payload but is not part of target schema."
            )
        )

    # Re-evaluate Severity based on proposals
    unresolved_required = [
        p.target_column for p in proposals
        if p.drift_type == DriftType.MISSING_REQUIRED and p.target_column
    ]

    updated_report = report.model_copy()
    updated_report.proposals = proposals

    if unresolved_required:
        updated_report.severity = DriftSeverity.BREAKING
        updated_report.diagnostics.append(f"Healing blocked: Missing required fields {unresolved_required} cannot be satisfied.")
    elif any(p.drift_type == DriftType.RENAMED_COLUMN for p in proposals) or default_fillers:
        updated_report.severity = DriftSeverity.HEALABLE
        updated_report.diagnostics.append("Automatic healing plan prepared successfully. Ready for human review/execution.")
    else:
        updated_report.severity = DriftSeverity.CLEAN

    adapter = AdapterRule(
        column_mapping=col_mapping,
        date_formats=date_formats,
        clean_numeric_columns=clean_numeric,
        default_fillers=default_fillers
    )

    return updated_report, adapter
