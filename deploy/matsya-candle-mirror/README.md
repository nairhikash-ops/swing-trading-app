# Matsya candle mirror

This deployment keeps `matsya.ohlcv_daily` on the swing server synchronized
from the new primary VPS without exposing PostgreSQL or copying Dhan tokens.

- The primary export account is restricted to the forced `primary-export.sh`
  command.
- The initial run makes a compressed custom-format database backup on the
  swing server and replaces only `matsya.ohlcv_daily`.
- For the backtesting-only swing host, daily runs transfer a complete candle
  snapshot and replace the target table in one transaction. This repairs any
  old or locally missing candle, not only recently updated rows.
- The watermark advances only after a successful target transaction.
- The swing-server runner executes once daily at 06:30 IST, after the primary
  OHLCV fetch window, and rotates its log at 10 MiB.
- The swing server's own OHLCV worker must remain disabled to preserve the
  single-writer design.
- PostgreSQL is never published to a public interface.
