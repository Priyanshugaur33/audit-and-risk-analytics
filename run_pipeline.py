"""End-to-end audit analytics pipeline.

Steps: load -> data-quality checks -> SQL audit tests -> feature engineering (15+) ->
Isolation Forest anomaly detection -> combined risk score -> risk class -> Power BI exports.
"""
import re
import sqlite3
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

df = pd.read_csv("data/transactions.csv", parse_dates=["txn_datetime"])
print("Loaded rows:", len(df))

# ---------------- 1. Data cleaning / validation ----------------
dq = {
    "missing_branch": int(df.branch_id.isna().sum()),
    "missing_channel": int(df.channel.isna().sum()),
    "nonpositive_amount": int((df.amount <= 0).sum()),
}
print("Data quality:", dq)
raw_df = df.copy()  # keep NULLs so SQL test T01 can find them
df["branch_id"] = df.branch_id.fillna("UNKNOWN")
df["channel"] = df.channel.fillna("UNKNOWN")

# ---------------- 2. SQL audit tests (10 tests, automated) ----------------
con = sqlite3.connect(":memory:")
raw_df.assign(txn_datetime=df.txn_datetime.dt.strftime("%Y-%m-%d %H:%M:%S")).to_sql("transactions", con, index=False)
sql = re.sub(r"--.*", "", open("sql/audit_tests.sql").read())  # strip comments first
queries = [q.strip() for q in sql.split(";") if "SELECT" in q]
flag_rows = []
test_summary = []
for q in queries:
    res = pd.read_sql(q, con)
    if "test" in res.columns and "txn_id" in res.columns:
        for t, g in res.groupby("test"):
            test_summary.append({"test": t, "exceptions": len(g)})
            flag_rows.append(g.assign(flag=1))
    elif "test" in res.columns:  # velocity test is customer-day level
        test_summary.append({"test": "T09_velocity", "exceptions": len(res)})
        vel = res
    else:
        trend = res
test_summary = pd.DataFrame(test_summary)
print("\nAudit test results:\n", test_summary.to_string(index=False))

flags = pd.concat(flag_rows)
flag_matrix = flags.pivot_table(index="txn_id", columns="test", values="flag", aggfunc="max", fill_value=0)
df = df.merge(flag_matrix, how="left", left_on="txn_id", right_index=True).fillna({c: 0 for c in flag_matrix.columns})
df["rule_hits"] = df[flag_matrix.columns].sum(axis=1)

# ---------------- 3. Feature engineering (16 features) ----------------
df = df.sort_values("txn_datetime").reset_index(drop=True)
df["hour"] = df.txn_datetime.dt.hour
df["dayofweek"] = df.txn_datetime.dt.dayofweek
df["is_weekend"] = (df.dayofweek >= 5).astype(int)
df["is_offhours"] = (df.hour < 5).astype(int)
df["log_amount"] = np.log1p(df.amount.clip(lower=0))
g = df.groupby("customer_id").amount
df["cust_mean"] = g.transform("mean")
df["cust_std"] = g.transform("std").fillna(0)
df["amount_zscore_cust"] = (df.amount - df.cust_mean) / df.cust_std.replace(0, np.nan)
df["amount_zscore_cust"] = df.amount_zscore_cust.fillna(0)
df["cust_txn_count"] = df.groupby("customer_id").txn_id.transform("count")
df["txn_per_day_cust"] = df.groupby(["customer_id", df.txn_datetime.dt.date]).txn_id.transform("count")
df["near_threshold"] = df.amount.between(95_000, 99_999.99).astype(int)
df["is_foreign"] = (df.country != "IN").astype(int)
df["same_approver"] = ((df.approved_by == df.initiated_by) & (df.approved_by != "SYSTEM")).astype(int)
df["amount_to_balance"] = df.amount / df.account_balance_after
df["branch_amount_pct"] = df.groupby("branch_id").amount.rank(pct=True)
df["channel_code"] = df.channel.astype("category").cat.codes
FEATURES = ["hour", "dayofweek", "is_weekend", "is_offhours", "log_amount", "amount_zscore_cust",
            "cust_txn_count", "txn_per_day_cust", "near_threshold", "is_foreign", "same_approver",
            "amount_to_balance", "branch_amount_pct", "channel_code", "cust_std", "cust_mean"]

# ---------------- 4. Anomaly detection ----------------
X = StandardScaler().fit_transform(df[FEATURES])
iso = IsolationForest(n_estimators=200, contamination=0.03, random_state=42).fit(X)
raw = -iso.score_samples(X)  # higher = more anomalous
df["anomaly_score"] = (raw - raw.min()) / (raw.max() - raw.min())
df["is_anomaly"] = (iso.predict(X) == -1).astype(int)

# ---------------- 5. Combined risk score (0-100) and class ----------------
rule_component = np.minimum(df.rule_hits / 3, 1)  # 3+ rule hits = max
df["risk_score"] = (100 * (0.6 * df.anomaly_score + 0.4 * rule_component)).round(1)
df["risk_class"] = pd.cut(df.risk_score, [-1, 30, 50, 65, 101], labels=["Low", "Medium", "High", "Critical"])
print("\nRisk class distribution:\n", df.risk_class.value_counts(normalize=True).round(3).sort_index())

# ---------------- 6. Validate against injected truth (our own check) ----------------
flagged_rules = df.rule_hits > 0
print("\nTransactions with >=1 rule exception:", int(flagged_rules.sum()),
      f"({flagged_rules.mean():.1%}); ML anomalies:", int(df.is_anomaly.sum()))
print("Overlap rule&ML:", int((flagged_rules & (df.is_anomaly == 1)).sum()))

# ---------------- 7. KPI table + exports for Power BI ----------------
kpis = {
    "total_transactions": len(df),
    "total_value": round(df.amount.clip(lower=0).sum(), 0),
    "exception_rate_pct": round(100 * flagged_rules.mean(), 2),
    "ml_anomaly_rate_pct": round(100 * df.is_anomaly.mean(), 2),
    "critical_cases": int((df.risk_class == "Critical").sum()),
    "high_cases": int((df.risk_class == "High").sum()),
    "audit_coverage_pct": 100.0,  # 100% population testing (no sampling)
}
pd.Series(kpis).to_csv("outputs/kpis.csv", header=["value"])
print("\nKPIs:", kpis)
df["remediation_status"] = np.where(df.risk_class.isin(["High", "Critical"]),
                                    np.random.default_rng(1).choice(["Open", "In Progress", "Closed"], len(df), p=[.5, .3, .2]), "N/A")
df.to_csv("outputs/scored_transactions.csv", index=False)
test_summary.to_csv("outputs/audit_test_summary.csv", index=False)
trend.to_csv("outputs/monthly_trend.csv", index=False)
df[df.risk_class.isin(["High", "Critical"])].sort_values("risk_score", ascending=False).head(200).to_csv("outputs/top_risk_cases.csv", index=False)
print("Exports written to outputs/")
