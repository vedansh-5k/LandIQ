"""
state.py
--------
Shared state for LandIQ.
"""

from typing import TypedDict, Annotated, Optional
from operator import add
from src.schemas.outputs import (
    LocationOutput, LegalOutput, FinancialOutput,
    MarketOutput, BullCaseOutput, BearCaseOutput,
    DueDiligenceOutput, FinalRecommendation
)


class LandQueryState(TypedDict):
    # User inputs
    state: str
    city: str
    area: str
    pincode: str
    land_size: float
    land_unit: str
    land_type: str
    has_title_deed: bool
    total_budget: float
    construction_budget: float
    taking_loan: bool
    loan_amount: float
    loan_interest_rate: float
    purpose: str
    timeline_years: int
    monthly_income_expectation: float
    risk_tolerance: str
    selected_agents: list

    # RAG
    rag_context: str

    # Layer 1
    location_output: Optional[LocationOutput]
    legal_output: Optional[LegalOutput]
    financial_output: Optional[FinancialOutput]
    market_output: Optional[MarketOutput]

    # Layer 2
    bull_output: Optional[BullCaseOutput]
    bear_output: Optional[BearCaseOutput]

    # Layer 3
    due_diligence_output: Optional[DueDiligenceOutput]

    # Final
    final_recommendation: Optional[FinalRecommendation]

    # Token tracking
    token_report: dict

    # Tracking
    completed_agents: Annotated[list, add]
    error_log: Annotated[list, add]