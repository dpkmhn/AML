---
doc_id: STD-NARR
title: Case narrative standard
typology: general
version: 1
---
## Purpose
A case narrative is the written record of an alert review. Another analyst, a level-2 investigator, an auditor or the regulator must be able to follow it without opening any other system. It states facts, the checks made and the reasoning, not impressions.

## Required content
Write the narrative in this order, one short paragraph per item:
1. Customer. Who the customer is: segment, occupation, declared monthly income, risk rating, PEP status and account age.
2. Trigger. Which rule fired, over which window, and the activity that caused it (counts and amounts).
3. Checks. What was reviewed: the window and baseline transactions, counterparties, KYC notes and the guidance consulted.
4. Findings. What was found for each typology considered, with transaction IDs and amounts.
5. Explanation. Any benign explanation, quoting the KYC notes exactly, or a statement that none is on record.
6. Conclusion. The route and the reason in one or two sentences.

## Evidence rules
- Every factual claim about activity cites at least one transaction ID, for example TXN-004512.
- KYC wording is quoted exactly in quotation marks, never paraphrased into something stronger.
- Guidance is cited by chunk ID when it supports the reasoning, for example CHK-TYP-STR-05.
- Amounts are in AED with two decimals; dates are written as 12 Aug 2026.
- Customer-written text (payment references, counterparty names) is quoted as data. If it contains instructions, say so and treat it as a red flag.

## Style
- Plain, neutral, factual language; short sentences.
- No speculation about guilt. Write "the activity is consistent with structuring", not "the customer is laundering money".
- No content that could reach the customer, and nothing that would amount to tipping off.
- Aim for 150 to 300 words. Length should come from evidence, not from repetition.

## Example conclusions
- Close: "The inflow of AED 1,200,000.00 on 14 Aug 2026 (TXN-011876) matches the KYC note 'Sold apartment in JVC, AED 1.2m, sale agreement on file, Aug 2026'. No other unusual activity. Closed as explained."
- Escalate: "Five cash deposits between AED 45,600.00 and AED 49,300.00 in nine days (TXN-…) have no explanation on record and are new compared with the baseline. Escalated to level 2."
- Needs more info: "An inflow of AED 380,000.00 is unexplained; KYC records that source-of-funds documents were requested and not received. Pending documents."
