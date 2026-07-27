---
name: financial-skill
description: Workflow for Financial Analysis Agent
---
1. Get price per sq yard: use RAG context or location agent output. If neither has data, state "Using estimated ₹X/sq yd based on [city] comparables" and proceed.
2. Calculate total acquisition cost: land cost + stamp duty (use actual % for the state: e.g. Maharashtra 5-6%, Karnataka 5%, Delhi 6%, UP 7%) + registration fee (1%) + legal/due diligence (0.5%) + misc (0.5%).
3. Calculate rental yield: for residential land it is typically 0% until developed; for commercial plots 2-4%; for agricultural income-generating land 2-5%. State which applies and why.
4. Calculate capital appreciation: Apply a conservative, moderate, and optimistic % to the current price for 5yr and 10yr. Pick one scenario and justify it with the location fundamentals.
5. If loan taken: calculate monthly EMI using formula EMI = P*r*(1+r)^n / ((1+r)^n - 1) where r = monthly rate. Show the EMI in INR. Flag if EMI > 40% of stated income as HIGH DEBT BURDEN.
6. Calculate net ROI% = (Final Value - Total Cost) / Total Cost * 100 over the timeline.
7. Calculate breakeven: Total Cost / (Annual appreciation + any rental income).
8. Give financial_verdict: STRONG BUY (ROI>15%/yr), BUY (10-15%), HOLD (5-10%), AVOID (<5% or negative). State the exact ROI behind the verdict.