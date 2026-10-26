-- Audit tests (SQLite syntax; works in MySQL/PostgreSQL with minor date-function changes).
-- Table: transactions(txn_id, txn_datetime, customer_id, branch_id, channel, txn_type,
--                     amount, country, approved_by, initiated_by, account_balance_after)

-- T01 Completeness: missing mandatory fields
SELECT 'T01_missing_fields' AS test, txn_id FROM transactions
WHERE branch_id IS NULL OR channel IS NULL OR amount IS NULL;

-- T02 Validity: non-positive amounts
SELECT 'T02_nonpositive_amount' AS test, txn_id FROM transactions WHERE amount <= 0;

-- T03 Duplicates: same customer, amount, type within 10 minutes
SELECT 'T03_duplicate' AS test, b.txn_id
FROM transactions a JOIN transactions b
  ON a.customer_id = b.customer_id AND a.amount = b.amount AND a.txn_type = b.txn_type
 AND a.txn_id < b.txn_id
 AND ABS(strftime('%s', a.txn_datetime) - strftime('%s', b.txn_datetime)) <= 600;

-- T04 Maker-checker (segregation of duties): same user initiated and approved
SELECT 'T04_maker_checker' AS test, txn_id FROM transactions
WHERE approved_by = initiated_by AND approved_by <> 'SYSTEM';

-- T05 Large transactions: above 99.5th percentile approximated by a fixed 300,000 cut-off
SELECT 'T05_large_txn' AS test, txn_id FROM transactions WHERE amount >= 300000;

-- T06 Structuring: just below the 100,000 reporting threshold
SELECT 'T06_structuring' AS test, txn_id FROM transactions
WHERE amount BETWEEN 95000 AND 99999.99;

-- T07 Off-hours large transactions (00:00-05:00, amount >= 50,000)
SELECT 'T07_offhours_large' AS test, txn_id FROM transactions
WHERE CAST(strftime('%H', txn_datetime) AS INTEGER) < 5 AND amount >= 50000;

-- T08 High-risk geography
SELECT 'T08_foreign_high_value' AS test, txn_id FROM transactions
WHERE country <> 'IN' AND amount >= 100000;

-- T09 Velocity: customers with more than 3 transactions on the same day
SELECT 'T09_velocity' AS test, customer_id, date(txn_datetime) AS d, COUNT(*) AS n
FROM transactions GROUP BY customer_id, date(txn_datetime) HAVING COUNT(*) > 3;

-- T10 Trend: monthly transaction count and value
SELECT strftime('%Y-%m', txn_datetime) AS month, COUNT(*) AS n, ROUND(SUM(amount),0) AS total
FROM transactions GROUP BY month ORDER BY month;
