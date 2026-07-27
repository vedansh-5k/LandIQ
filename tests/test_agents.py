"""
test_agents.py
--------------
End to end test of the complete Land Investment Advisor.

Simulates a user who wants to buy land in Gurugram Sector 65
and runs through all 8 agents to verify everything works.

Run with: python tests/test_agents.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.graph.orchestrator import run_land_advisor


def test_full_system():
    """
    Tests the complete 8-agent pipeline with a realistic
    Indian land investment scenario.

    This simulates exactly what happens when a user
    submits the form in the browser.
    """

    print("\n" + "="*60)
    print("RUNNING END TO END TEST")
    print("Scenario: Commercial plot in Gurugram Sector 65")
    print("="*60 + "\n")

    # Simulate user form inputs
    test_inputs = {
        "state": "Haryana",
        "city": "Gurugram",
        "area": "Sector 65",
        "pincode": "122101",
        "land_size": 500,
        "land_unit": "sq_yards",
        "land_type": "commercial",
        "has_title_deed": True,
        "total_budget": 5000000,
        "construction_budget": 2000000,
        "taking_loan": False,
        "loan_amount": 0,
        "loan_interest_rate": 0,
        "purpose": "Build commercial shops and rent them out",
        "timeline_years": 10,
        "monthly_income_expectation": 50000,
        "risk_tolerance": "moderate"
    }

    print("Input Details:")
    for key, value in test_inputs.items():
        print(f"  {key}: {value}")
    print()

    # Run the complete system
    result = run_land_advisor(test_inputs)

    # Print results
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)

    print(f"\nAgents Completed: {result.get('completed_agents', [])}")
    print(f"Errors: {result.get('error_log', [])}")

    loc = result.get("location_output")
    if loc:
        print(f"\nLOCATION AGENT:")
        print(f"  Score: {loc.location_score}/100")
        print(f"  Price Range: {loc.current_price_range}")
        print(f"  Summary: {loc.summary}")

    leg = result.get("legal_output")
    if leg:
        print(f"\nLEGAL AGENT:")
        print(f"  Risk Level: {leg.legal_risk_level}")
        print(f"  Land Type: {leg.land_type}")
        print(f"  Summary: {leg.summary}")

    fin = result.get("financial_output")
    if fin:
        print(f"\nFINANCIAL AGENT:")
        print(f"  ROI 5yr: {fin.roi_5_year}%")
        print(f"  ROI 10yr: {fin.roi_10_year}%")
        print(f"  Breakeven: {fin.breakeven_years} years")
        print(f"  Viability: {fin.financial_viability}")
        print(f"  Summary: {fin.summary}")

    mkt = result.get("market_output")
    if mkt:
        print(f"\nMARKET AGENT:")
        print(f"  Score: {mkt.market_score}/100")
        print(f"  Demand: {mkt.current_demand}")
        print(f"  Summary: {mkt.summary}")

    bull = result.get("bull_output")
    if bull:
        print(f"\nBULL CASE:")
        print(f"  Conviction: {bull.conviction_level}")
        print(f"  Summary: {bull.summary}")

    bear = result.get("bear_output")
    if bear:
        print(f"\nBEAR CASE:")
        print(f"  Conviction: {bear.conviction_level}")
        print(f"  Summary: {bear.summary}")

    dd = result.get("due_diligence_output")
    if dd:
        print(f"\nDUE DILIGENCE:")
        print(f"  Credibility: {dd.overall_credibility}")
        print(f"  Summary: {dd.summary}")

    rec = result.get("final_recommendation")
    if rec:
        print(f"\nFINAL RECOMMENDATION:")
        print(f"  Verdict: {rec.final_verdict}")
        print(f"  Confidence: {rec.confidence_level}")
        print(f"  Executive Summary: {rec.executive_summary}")
        print(f"\nDocuments Checklist:")
        for doc in rec.documents_checklist:
            print(f"    - {doc}")
        print(f"\nNext Steps:")
        for step in rec.next_steps:
            print(f"    - {step}")

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60 + "\n")


if __name__ == "__main__":
    test_full_system()