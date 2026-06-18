import sqlite3
import json
import os

conn = sqlite3.connect('/app/data/dhan_auth.sqlite3')
conn.row_factory = sqlite3.Row

queries = [
    ('ml_samples_TESTSYM_count', "select count(*) c from ml_samples where upper(symbol)='TESTSYM'"),
    ('instruments_TESTSYM_count', "select count(*) c from instruments where upper(underlying_symbol)='TESTSYM'"),
    ('daily_candles_by_instrument', "select count(*) c from daily_candles where instrument_id in (select id from instruments where upper(underlying_symbol)='TESTSYM')"),
]

for name, q in queries:
    try:
        print(name + ':', conn.execute(q).fetchone()['c'])
    except Exception as e:
        print(name + '_error:', e)

print('ml_samples_total:', conn.execute('select count(*) c from ml_samples').fetchone()['c'])

paths = [
    '/app/data/exports/ml_dataset_ohlcv_v1.csv',
    '/app/data/exports/ml_dataset_ohlcv_regime_v1.csv',
    '/app/data/exports/latest_regime_rankings.meta.json',
    '/app/data/exports/shadow_performance_summary.json',
    '/app/data/exports/shadow_performance_report_v1.txt',
]
for p in paths:
    print(p, 'exists:', os.path.exists(p), 'size:', os.path.getsize(p) if os.path.exists(p) else None)

meta = '/app/data/exports/latest_regime_rankings.meta.json'
if os.path.exists(meta):
    print('ranking_meta:', json.load(open(meta)))

summary = '/app/data/exports/shadow_performance_summary.json'
if os.path.exists(summary):
    print('shadow_summary_keys:', sorted(json.load(open(summary)).keys()))
