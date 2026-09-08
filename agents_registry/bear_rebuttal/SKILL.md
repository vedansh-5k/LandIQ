---
name: bear_rebuttal-skill
description: Workflow for Bear Rebuttal Agent
---
1. Read the Bull Case Agent's output from PRIOR AGENT FINDINGS in full — top_upside_triggers, best_case_price_5yr, best_case_price_10yr, best_case_total_return, catalyst_timeline, bull_probability.
2. For EACH specific trigger bull raised, respond directly: name the trigger, then either (a) explain specifically why it's overstated, unconfirmed, or likely to slip in timeline for THIS property using facts already gathered (STRUCTURED FACTS, RAG, location/legal/market agent findings), or (b) concede it is a real, credible catalyst.
3. Do not manufacture a rebuttal to every point just to seem thorough — if bull's infrastructure catalyst is genuinely funded and under construction with a firm date, concede it in upside_bear_concedes rather than arguing it away.
4. Check bull's best-case return math: is the optimistic appreciation assumption bull used reasonable, or does it ignore a specific downside factor (legal risk, liquidity, macro headwind) that bear already identified?
5. Write the revised_bear_case: state plainly whether the original worst-case loss still holds once bull's valid catalysts are priced in, or whether the realistic downside is now smaller — give a number if possible.
6. Give debate_verdict: STRONG if bull's triggers don't meaningfully change the bear thesis, WEAKENED if some real catalysts reduce the risk but concerns remain, REFUTED if bull's catalysts are credible enough that the bear case does not hold up.
