# Audit & Risk Analytics Platform

An automated audit-analytics workflow for banking transactions. It tests **100% of transactions** (no sampling) using SQL audit tests, adds machine-learning anomaly detection, and ranks every transaction by a **risk score** so auditors can review the riskiest cases first.

## The problem

Traditional audits review a small sample of transactions, so control failures can be missed. This project automates population-wide testing and prioritises review effort by risk.

## Pipeline

```
Raw transactions (CSV)
   -> Data-quality validation (nulls, non-positive amounts)
   -> 10 SQL audit tests (rule-based exceptions)
   -> Feature engineering (16 features)
   -> Isolation Forest (unsupervised anomaly score)
   -> Risk score = 60% ML anomaly score + 40% rule hits  ->  Low / Medium / High / Critical
   -> CSV exports for a Power BI dashboard
```

## Audit tests (`sql/audit_tests.sql`)

| ID | Test | What it catches |
|---|---|---|
| T01 | Missing mandatory fields | Incomplete records |
| T02 | Non-positive amounts | Invalid data, possible reversal abuse |
| T03 | Duplicate transactions | Same customer, amount and type within 10 minutes |
| T04 | Maker-checker breach | Same user initiated and approved (segregation of duties) |
| T05 | Large transactions | Amount >= 300,000 |
| T06 | Structuring | Amounts between 95,000 and 99,999 (just under a 100,000 threshold) |
| T07 | Off-hours large | 00:00-05:00 and amount >= 50,000 |
| T08 | Foreign high value | Non-domestic and amount >= 100,000 |
| T09 | Velocity | More than 3 transactions by one customer in a day |
| T10 | Monthly trend | Count and value by month |

## Features (16)

hour, day of week, weekend flag, off-hours flag, log amount, customer-wise amount z-score, customer transaction count, transactions per customer per day, near-threshold flag, foreign flag, same-approver flag, amount-to-balance ratio, branch amount percentile, channel code, customer amount std, customer amount mean.

The customer-wise z-score is the key one: an amount that is normal for one customer can be highly unusual for another.

## Model and risk score

- **Isolation Forest** (200 trees, `contamination=0.03`) on standardised features. It needs no fraud labels and isolates rare, different points in fewer splits.
- **Risk score (0-100)** = `100 x (0.6 x normalised anomaly score + 0.4 x min(rule_hits / 3, 1))`
- **Bands:** Low (<=30), Medium (30-50), High (50-65), Critical (>65). The weights and bands are judgement calls and should be calibrated with auditor feedback.

## Results on the synthetic data

| Metric | Value |
|---|---|
| Transactions tested | 20,050 (100% coverage) |
| Transactions with at least one rule exception | 616 (3.1%) |
| Flagged by Isolation Forest | 602 (3.0%) |
| Flagged by both rules and ML | 326 |
| High-risk cases | 211 |
| Critical cases | 92 |

Exceptions per test: T01 110, T02 40, T03 50, T04 100, T05 120, T06 103, T07 147, T08 10, T09 0 (no customer exceeded the velocity limit in this synthetic data).

Reviewers look at roughly 300 High/Critical cases (211 + 92) instead of 20,000 transactions.

## Run it

```bash
pip install -r requirements.txt
python generate_data.py     # creates data/transactions.csv (synthetic)
python run_pipeline.py      # runs tests, features, model, scoring; writes outputs/
```

## Outputs (`outputs/`)

| File | Contents |
|---|---|
| `scored_transactions.csv` | Every transaction with rule flags, features, anomaly score, risk score, risk class |
| `audit_test_summary.csv` | Exceptions per audit test |
| `top_risk_cases.csv` | Highest-risk cases for review |
| `monthly_trend.csv` | Monthly count and value |
| `kpis.csv` | Headline KPIs |

These CSVs can be loaded into Power BI (Get Data > Text/CSV) for a dashboard with KPIs such as total transactions, total value, exception rate, ML anomaly rate, critical and high cases, exceptions by test, monthly trend, and remediation status.

## Limitations

- **No ground-truth labels.** Precision and recall can't be measured directly. Validation here is the overlap between ML flags and rule exceptions plus review of top-ranked cases.
- **Assumptions.** The contamination rate, score weights and band cut-offs are assumptions.
- **Explainability.** Isolation Forest does not say why a row was flagged.
- **Synthetic data.** Injected anomalies are easier to detect than real-world fraud.

## Next steps

Collect auditor decisions as labels and train a supervised model, add SHAP explanations, calibrate thresholds, schedule runs, and add alerting.

## Tech stack

Python, pandas, NumPy, scikit-learn, SQL (SQLite syntax), Power BI.
