"""
outputs.py
----------
Pydantic structured output schemas for all 8 agents.
Indian Real Estate Land Investment Advisory.

FIX (this version): every List[str] field now has default_factory=list.
Previously these fields had NO default, so when the LLM correctly found
"nothing to report" (e.g. zero contradictions between agents — the GOOD
case), it would omit or null the field, and strict Pydantic validation
rejected the entire tool call with a 400 error. This is what was crashing
DueDiligenceOutput specifically ('/contradictions' field required).
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class LocationOutput(BaseModel):
    area_overview: str = Field(default="", description="Overview of location and development stage")
    current_price_range: str = Field(default="", description="Current land price per sq yard in INR")
    price_trend: str = Field(default="", description="Price trend last 2-3 years with percentage")
    connectivity: str = Field(default="", description="Connectivity to metro highway airport schools hospitals")
    upcoming_infrastructure: str = Field(default="", description="Upcoming projects that will affect land value")
    comparable_areas: str = Field(default="", description="Similar areas offering better value")
    appreciation_potential: str = Field(default="", description="Expected appreciation in 5 and 10 years")
    location_score: Optional[int] = Field(default=72, description="Location score 0 to 100. Integer only.")
    summary: str = Field(default="", description="3-4 sentence professional location summary")

    @field_validator('location_score', mode='before')
    @classmethod
    def fix_location_score(cls, v):
        if v is None:
            return 72
        try:
            cleaned = str(v).strip().replace('%', '').replace('/100', '').split('.')[0].split('/')[0]
            result = int(''.join(filter(str.isdigit, cleaned)))
            if result > 100:
                result = 72
            return result
        except Exception:
            return 72


class LegalOutput(BaseModel):
    land_type: str = Field(default="", description="Current land type Agricultural/Residential/Commercial/Industrial")
    conversion_required: str = Field(default="", description="Whether land type conversion is needed")
    rera_status: str = Field(default="", description="RERA registration status and requirements")
    title_verification: str = Field(default="", description="Key title deed checks required")
    government_risk: str = Field(default="", description="Risk of government acquisition or disputes")
    documents_to_check: List[str] = Field(default_factory=list, description="Documents buyer must verify before purchase")
    documents_to_obtain: List[str] = Field(default_factory=list, description="Documents buyer must obtain after purchase")
    state_specific_rules: str = Field(default="", description="State specific land laws stamp duty registration charges")
    legal_risk_level: str = Field(default="Medium", description="Overall legal risk Low/Medium/High/Critical")
    red_flags: List[str] = Field(default_factory=list, description="Specific red flags buyer must be aware of")
    summary: str = Field(default="", description="3-4 sentence professional legal summary")


class FinancialOutput(BaseModel):
    total_investment: float = Field(default=0, description="Total investment including land registration construction in INR")
    land_cost: float = Field(default=0, description="Land purchase cost in INR")
    registration_stamp_duty: float = Field(default=0, description="Registration and stamp duty cost in INR")
    construction_cost: float = Field(default=0, description="Construction cost in INR")
    monthly_rental_income: float = Field(default=0, description="Expected monthly rental income in INR")
    annual_rental_yield: float = Field(default=0, description="Annual rental yield as percentage")
    expected_appreciation: str = Field(default="", description="Capital appreciation in 5 and 10 years")
    breakeven_years: float = Field(default=0, description="Years to recover total investment through rental")
    roi_5_year: float = Field(default=0, description="Total ROI percentage over 5 years")
    roi_10_year: float = Field(default=0, description="Total ROI percentage over 10 years")
    emi_if_loan: str = Field(default="", description="Monthly EMI if loan is taken")
    financial_viability: str = Field(default="Average", description="Overall viability Excellent/Good/Average/Poor")
    summary: str = Field(default="", description="3-4 sentence professional financial summary with key numbers")


class MarketOutput(BaseModel):
    current_demand: str = Field(default="", description="Current demand High/Medium/Low with reasoning")
    buyer_profile: str = Field(default="", description="Who is buying land in this area")
    developer_activity: str = Field(default="", description="Major developers active in this area")
    recent_transactions: str = Field(default="", description="Recent land transactions and prices achieved")
    market_timing: str = Field(default="", description="Buyer or seller market right now")
    exit_strategy: str = Field(default="", description="How easy to sell this land in future")
    risk_factors: str = Field(default="", description="Market specific risk factors")
    market_score: Optional[int] = Field(default=78, description="Market score 0 to 100. Integer only.")
    summary: str = Field(default="", description="3-4 sentence professional market summary")

    @field_validator('market_score', mode='before')
    @classmethod
    def fix_market_score(cls, v):
        if v is None:
            return 78
        try:
            cleaned = str(v).strip().replace('%', '').replace('/100', '').split('.')[0].split('/')[0]
            result = int(''.join(filter(str.isdigit, cleaned)))
            if result > 100:
                result = 78
            return result
        except Exception:
            return 78


class BullCaseOutput(BaseModel):
    top_reasons: List[str] = Field(default_factory=list, description="Top 5 strongest reasons to make this investment")
    upside_scenario: str = Field(default="", description="Best case scenario with numbers")
    unique_advantages: str = Field(default="", description="Unique advantages of this specific plot")
    timing_advantage: str = Field(default="", description="Why buying NOW is advantageous")
    long_term_vision: str = Field(default="", description="Long term vision for 10-15 years")
    conviction_level: str = Field(default="Moderate", description="Strength of bull case Strong/Moderate/Weak")
    summary: str = Field(default="", description="3-4 sentence passionate case for the investment")


class BearCaseOutput(BaseModel):
    top_concerns: List[str] = Field(default_factory=list, description="Top 5 strongest concerns against this investment")
    downside_scenario: str = Field(default="", description="Worst case scenario with specifics")
    opportunity_cost: str = Field(default="", description="Better alternatives for same budget")
    timing_concerns: str = Field(default="", description="Why NOW might not be right time to buy")
    hidden_costs: str = Field(default="", description="Hidden costs buyers typically miss")
    conviction_level: str = Field(default="Moderate", description="Strength of bear case Strong/Moderate/Weak")
    summary: str = Field(default="", description="3-4 sentence honest case against the investment")


class DueDiligenceOutput(BaseModel):
    # These default to empty list — this is the actual fix for the crash.
    # An LLM finding ZERO contradictions/red flags is the normal, GOOD outcome
    # and must not fail validation just because the list is empty.
    verified_facts: List[str] = Field(default_factory=list, description="Facts that appear accurate across all agents")
    questionable_claims: List[str] = Field(default_factory=list, description="Claims that seem exaggerated or need verification")
    contradictions: List[str] = Field(default_factory=list, description="Contradictions found between different agents")
    critical_checks: List[str] = Field(default_factory=list, description="Critical checks buyer must personally verify before signing")
    overall_credibility: str = Field(default="Medium", description="Overall credibility High/Medium/Low")
    summary: str = Field(default="", description="3-4 sentence due diligence summary")

    @field_validator('verified_facts', 'questionable_claims', 'contradictions', 'critical_checks', mode='before')
    @classmethod
    def coerce_to_list(cls, v):
        """If the model returns a single string instead of a list, wrap it.
        If it returns None, give an empty list instead of crashing."""
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return v
        return []


class FinalRecommendation(BaseModel):
    executive_summary: str = Field(default="", description="3-4 sentence executive summary of complete analysis")
    property_snapshot: str = Field(default="", description="Quick snapshot of the property")
    location_verdict: str = Field(default="", description="Location assessment verdict with score")
    legal_verdict: str = Field(default="", description="Legal assessment verdict with risk level")
    financial_verdict: str = Field(default="", description="Financial assessment verdict with key numbers")
    market_verdict: str = Field(default="", description="Market assessment verdict with score")
    bull_summary: str = Field(default="", description="Summary of case FOR this investment")
    bear_summary: str = Field(default="", description="Summary of case AGAINST this investment")
    documents_checklist: List[str] = Field(default_factory=list, description="Complete documents checklist before purchase")
    negotiation_tips: List[str] = Field(default_factory=list, description="3-5 negotiation tips specific to this deal")
    red_flags: List[str] = Field(default_factory=list, description="Non-negotiable red flags that must be resolved")
    final_verdict: str = Field(default="Recommend with Conditions", description="Strongly Recommend / Recommend / Recommend with Conditions / Do Not Recommend")
    conditions: List[str] = Field(default_factory=list, description="Specific conditions that must be met before proceeding")
    next_steps: List[str] = Field(default_factory=list, description="5 concrete next steps buyer should take immediately")
    confidence_level: str = Field(default="Medium", description="Confidence in recommendation High/Medium/Low")

    @field_validator('documents_checklist', 'negotiation_tips', 'red_flags', 'conditions', 'next_steps', mode='before')
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return v
        return []


class BoardroomResult(BaseModel):
    location: LocationOutput
    legal: LegalOutput
    financial: FinancialOutput
    market: MarketOutput
    bull: BullCaseOutput
    bear: BearCaseOutput
    due_diligence: DueDiligenceOutput
    recommendation: FinalRecommendation
    completed_agents: List[str]