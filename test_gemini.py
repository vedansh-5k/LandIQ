import requests
import json

payload = {
    "state": "Haryana",
    "city": "Gurugram",
    "area": "Sector 44",
    "pincode": "",
    "land_size": 200,
    "land_unit": "sq_yards",
    "land_type": "residential",
    "has_title_deed": True,
    "total_budget": 50000000,
    "construction_budget": 0,
    "taking_loan": False,
    "loan_amount": 0,
    "loan_interest_rate": 0,
    "purpose": "investment",
    "timeline_years": 10,
    "monthly_income_expectation": 0,
    "risk_tolerance": "moderate",
    "selected_agents": ["location"],
    "caveman_mode": False,
    "caveman_level": "full",
    "selected_model": "gemini-1.5-flash"
}

print("Testing Gemini...")
try:
    res = requests.post("http://localhost:8000/analyse", json=payload)
    print("STATUS:", res.status_code)
    data = res.json()
    print("Errors in response:", data.get("errors", []))
    print("Location Result:", data.get("location"))
except Exception as e:
    print("Failed:", e)
