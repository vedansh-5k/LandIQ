---
name: visual_document-skill
description: Workflow for Visual Document Intelligence Agent
---
1. Check whether `visual_evidence` (retrieved screenshot tiles) was provided at all. If empty or missing, set `visual_evidence_found: NO` and explain briefly why nothing is being reported — do not fabricate table contents.
2. If tiles were provided, look at each image directly. Identify what kind of content it is: a price/rate table, a land-use map, a market chart, a scanned document page, etc.
3. Read specific numbers off the image exactly as shown — INR figures, percentages, per-sq-yard/sq-ft rates, dates. Do not round or approximate beyond what the image shows.
4. Cross-check whether the retrieved page is actually about this property's location, city or land type. If the match looks weak or off-topic, say so in `visual_confidence` rather than forcing a connection.
5. Name the source document and page/tile for every finding so it can be traced back to the original screenshot.
6. In `visual_recommendation`, state concretely what this visual read added beyond what a text-only search could have found (e.g. "the rate table shows Sector 82 at Rs.X/sq yd, which the parsed-text RAG would have missed because it was inside a table image"), or say plainly that nothing new was added if that's the case.
