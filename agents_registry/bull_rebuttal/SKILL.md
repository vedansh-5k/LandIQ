---
name: bull_rebuttal-skill
description: Workflow for Bull Rebuttal Agent
---
1. Read the Bear Case Agent's output from PRIOR AGENT FINDINGS in full — top_downside_risks, worst_case_price_5yr, worst_case_loss_inr, liquidity_risk, legal_risk_flag, macro_risks, bear_probability.
2. For EACH specific risk bear raised, respond directly: name the risk, then either (a) explain specifically why it's overstated or unlikely for THIS property using facts already gathered (STRUCTURED FACTS, RAG, location/legal/market agent findings), or (b) concede it is a real, valid concern.
3. Do not manufacture a rebuttal to every point just to seem thorough — if bear's legal_risk_flag or a title/liquidity concern is genuinely serious, concede it in risks_bull_concedes rather than arguing it away.
4. Check bear's worst-case loss math: is the pessimistic appreciation assumption bear used reasonable, or does it ignore a specific positive catalyst (infrastructure, demand driver) that bull already identified?
5. Write the revised_bull_case: state plainly whether the original best-case return still holds once bear's valid risks are priced in, or whether the realistic upside is now lower — give a number if possible.
6. Give debate_verdict: STRONG if bear's risks don't meaningfully change the bull thesis, WEAKENED if some real risks reduce the case but upside still exists, REFUTED if bear's risks are serious enough that the bull case does not hold up.
