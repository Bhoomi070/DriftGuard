from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class DriftSeverity(str, Enum):
    CLEAN = "CLEAN"
    HEALABLE = "HEALABLE"
    BREAKING = "BREAKING"


class DriftType(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    RENAMED_COLUMN = "RENAMED_COLUMN"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    MISSING_OPTIONAL = "MISSING_OPTIONAL"
    UNEXPECTED_COLUMN = "UNEXPECTED_COLUMN"
    DATE_FORMAT_SHIFT = "DATE_FORMAT_SHIFT"


class FieldContract(BaseModel):
    name: str
    data_type: str  # string, float, int, date, boolean
    required: bool = True
    default: Optional[Any] = None
    allowed_values: Optional[List[str]] = None
    description: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)


class DataContract(BaseModel):
    name: str
    version: str
    description: Optional[str] = None
    fields: List[FieldContract]

    def get_field(self, name: str) -> Optional[FieldContract]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def required_fields(self) -> List[str]:
        return [f.name for f in self.fields if f.required]

    @property
    def optional_fields(self) -> List[str]:
        return [f.name for f in self.fields if not f.required]


class FieldMatchProposal(BaseModel):
    client_column: str
    target_column: Optional[str] = None
    confidence: float  # 0.0 to 1.0
    match_method: str  # "exact", "synonym", "fuzzy_name", "value_profiling"
    drift_type: DriftType
    sample_values: List[str] = Field(default_factory=list)
    reasoning: str


class DriftReport(BaseModel):
    contract_name: str
    contract_version: str
    severity: DriftSeverity
    total_contract_fields: int
    exact_matches: List[str] = Field(default_factory=list)
    missing_required: List[str] = Field(default_factory=list)
    missing_optional: List[str] = Field(default_factory=list)
    unexpected_client_columns: List[str] = Field(default_factory=list)
    proposals: List[FieldMatchProposal] = Field(default_factory=list)
    diagnostics: List[str] = Field(default_factory=list)


class AdapterRule(BaseModel):
    """Execution plan to translate client data into compliant contract format."""
    column_mapping: Dict[str, str] = Field(default_factory=dict)  # client_col -> target_col
    date_formats: Dict[str, str] = Field(default_factory=dict)     # col -> format to parse
    clean_numeric_columns: List[str] = Field(default_factory=list) # columns to strip '$', ','
    default_fillers: Dict[str, Any] = Field(default_factory=dict)  # missing target col -> default value
