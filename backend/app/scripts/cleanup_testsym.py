import sqlite3

db = '/app/data/dhan_auth.sqlite3'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

rows = conn.execute("select id, underlying_symbol from instruments where upper(underlying_symbol)='TESTSYM'").fetchall()
print('TESTSYM instruments found:', [dict(r) for r in rows])

ids = [r['id'] for r in rows]
if ids:
    qmarks = ','.join(['?'] * len(ids))
    candle_count = conn.execute(f'select count(*) from daily_candles where instrument_id in ({qmarks})', ids).fetchone()[0]
    sample_count = conn.execute("select count(*) from ml_samples where upper(symbol)='TESTSYM'").fetchone()[0]
    print('daily_candles_to_delete:', candle_count)
    print('ml_samples_testsym_count:', sample_count)

    conn.execute(f'delete from daily_candles where instrument_id in ({qmarks})', ids)
    conn.execute(f'delete from instruments where id in ({qmarks})', ids)
    conn.commit()
    print('cleanup executed.')
else:
    print('No TESTSYM instrument found - nothing to delete.')

print('after_instruments_TESTSYM:', conn.execute("select count(*) from instruments where upper(underlying_symbol)='TESTSYM'").fetchone()[0])
print('after_daily_candles_TESTSYM:', conn.execute("select count(*) from daily_candles where instrument_id in (select id from instruments where upper(underlying_symbol)='TESTSYM')").fetchone()[0])
print('after_ml_samples_TESTSYM:', conn.execute("select count(*) from ml_samples where upper(symbol)='TESTSYM'").fetchone()[0])
print('ml_samples_total:', conn.execute('select count(*) from ml_samples').fetchone()[0])
conn.close()
