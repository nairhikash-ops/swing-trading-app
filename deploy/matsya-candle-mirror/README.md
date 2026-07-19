# Matsya candle mirror

This deployment keeps `matsya.ohlcv_daily` on the swing server synchronized
from the new primary VPS without exposing PostgreSQL or copying Dhan tokens.

- The primary export account is restricted to the forced `primary-export.sh`
  command.
- The initial run makes a compressed custom-format database backup on the
  swing server and replaces only `matsya.ohlcv_daily`.
- Later runs transfer rows whose `updated_at` is at or after the last committed
  watermark and upsert them using `(provider_code, security_id, trading_date)`.
- The watermark advances only after a successful target transaction.
- The swing-server runner executes every two minutes and rotates its log at
  10 MiB.
- The swing server's own OHLCV worker must remain disabled to preserve the
  single-writer design.
- PostgreSQL is never published to a public interface.
