---
name: location-skill
description: Workflow for Location Intelligence Agent
---
1. Identify the exact micro-market from the RAG context: Is this area developing, developed, or saturated? State the development stage with evidence.
2. State current price per sq yard in INR for THIS area — not a city average. If RAG has data, cite it. If not, say "Estimated based on [nearby area] comparables: ₹X-Y per sq yard."
3. Describe the 2-3 year price trend with an actual % figure. Did prices rise, stagnate, or fall? Give one concrete reason.
4. Give actual km distances: nearest NH/expressway, nearest metro station (or planned), airport, schools, hospitals. Real numbers — not "well connected."
5. List upcoming infrastructure by NAME: which metro line extension, ring road, expressway, or SEZ will affect this area and when (expected year).
6. Name 1-2 comparable micro-markets in the same city offering similar or better value for the same budget and briefly explain why.
7. State appreciation potential as a % range: 5-year and 10-year. Back it with one specific driver (infra, employment zone, population growth).
8. Give location_score as integer 0-100. Be calibrated: 90+ = exceptional; 70-89 = good; 50-69 = average; below 50 = significant concerns.
9. Write a 3-4 sentence summary a paying client would trust. Include the price range, trend, and single most important upside or risk for this area.