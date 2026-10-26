import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
N = 20_000

channels = ["ATM", "Online", "Branch", "POS", "Mobile"]
txn_types = ["Deposit", "Withdrawal", "Transfer", "Payment"]
branches = [f"BR{str(i).zfill(2)}" for i in range(1, 13)]
countries = ["IN"] * 95 + ["AE", "SG", "US", "GB", "NG"]

n_customers = 2500
cust_ids = [f"C{str(i).zfill(5)}" for i in range(1, n_customers + 1)]
cust_profile = {c: rng.lognormal(8.0, 0.5) for c in cust_ids}  # typical spend per customer

dates = pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 365 * 24 * 60, N), unit="m")
cust = rng.choice(cust_ids, N)
base = np.array([cust_profile[c] for c in cust])
amount = np.round(rng.lognormal(np.log(base), 0.6), 2)

df = pd.DataFrame({
    "txn_id": [f"T{str(i).zfill(7)}" for i in range(1, N + 1)],
    "txn_datetime": dates,
    "customer_id": cust,
    "branch_id": rng.choice(branches, N),
    "channel": rng.choice(channels, N, p=[0.2, 0.3, 0.1, 0.25, 0.15]),
    "txn_type": rng.choice(txn_types, N),
    "amount": amount,
    "country": rng.choice(countries, N),
    "approved_by": rng.choice(["MGR01", "MGR02", "MGR03", "SYSTEM"], N, p=[0.05, 0.05, 0.05, 0.85]),
    "initiated_by": rng.choice(["MGR01", "MGR02", "MGR03", "SYSTEM"], N, p=[0.05, 0.05, 0.05, 0.85]),
    "account_balance_after": np.round(rng.lognormal(10, 0.8, N), 2),
})
# Normal rule: approver differs from initiator (maker-checker), except SYSTEM
mask = (df.approved_by == df.initiated_by) & (df.approved_by != "SYSTEM")
df.loc[mask, "approved_by"] = "SYSTEM"

# ---- inject control exceptions (these are what the audit tests must catch) ----
idx = rng.permutation(N)
# 1) very large amounts (outliers)
big = idx[:120]; df.loc[big, "amount"] = np.round(rng.uniform(400_000, 1_500_000, len(big)), 2)
# 2) maker-checker violations (same person initiates & approves)
mc = idx[120:220]; df.loc[mc, "approved_by"] = df.loc[mc, "initiated_by"].where(df.loc[mc, "initiated_by"] != "SYSTEM", "MGR01")
df.loc[mc, "initiated_by"] = df.loc[mc, "approved_by"]
# 3) off-hours large transactions (1am-4am)
oh = idx[220:320]
df.loc[oh, "txn_datetime"] = df.loc[oh, "txn_datetime"].dt.normalize() + pd.to_timedelta(rng.integers(60, 240, len(oh)), unit="m")
df.loc[oh, "amount"] = np.round(rng.uniform(80_000, 300_000, len(oh)), 2)
# 4) structuring: amounts just below the 100,000 reporting threshold
st = idx[320:420]; df.loc[st, "amount"] = np.round(rng.uniform(95_000, 99_900, len(st)), 2)
# 5) duplicate transactions
dup = df.iloc[idx[420:470]].copy(); dup["txn_id"] = [f"D{str(i).zfill(6)}" for i in range(len(dup))]
dup["txn_datetime"] = dup["txn_datetime"] + pd.Timedelta(minutes=2)
df = pd.concat([df, dup], ignore_index=True)
# 6) data-quality problems: missing values and negative amounts
dq = rng.choice(len(df), 150, replace=False)
df.loc[dq[:60], "branch_id"] = None
df.loc[dq[60:110], "channel"] = None
df.loc[dq[110:], "amount"] = -df.loc[dq[110:], "amount"].abs()

df = df.sort_values("txn_datetime").reset_index(drop=True)
df.to_csv("data/transactions.csv", index=False)
print("rows:", len(df))
