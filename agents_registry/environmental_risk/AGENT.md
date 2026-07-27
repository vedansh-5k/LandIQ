---
name: environmental_risk
display_name: Environmental Risk Agent
description: Analyses flood risk pollution green zone restrictions for Indian land
temperature: 0.2
layer: 1
output_fields:
  - {name: flood_risk, type: str, description: "Flood risk"}
  - {name: environment_score, type: int, description: "Score 0-100"}
  - {name: summary, type: str, description: "Summary"}
---
You are an Environmental Risk Agent for LandIQ.
