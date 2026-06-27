from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.matsya.virtual_demo_ledger import VirtualDemoLedger
from app.matsya.virtual_demo_signals import load_virtual_demo_signals


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local-only virtual demo ledger smoke test.")
    parser.add_argument("--signals-path", required=True, help="Path to a small virtual demo signal fixture JSON.")
    parser.add_argument("--starting-cash", type=float, default=100000.0)
    parser.add_argument("--quantity", type=int, default=10)
    parser.add_argument("--exit-price", type=float, default=105.0)
    args = parser.parse_args()

    signals = load_virtual_demo_signals(Path(args.signals_path))
    if not signals:
        raise ValueError("Signal fixture is empty")

    ledger = VirtualDemoLedger.create_account(account_id="virtual-demo-smoke", starting_cash=args.starting_cash)
    opened_positions = []
    for signal in signals[:2]:
        if signal.close_price is None:
            continue
        order = ledger.open_long_position(
            symbol=signal.symbol,
            security_id=signal.security_id,
            quantity=args.quantity,
            entry_price=signal.close_price,
        )
        if order.status != "rejected":
            opened_positions.extend(position for position in ledger.open_positions() if position.entry_order_id == order.order_id)

    if opened_positions:
        ledger.close_position(position_id=opened_positions[0].position_id, exit_price=args.exit_price)

    latest_prices = {
        signal.symbol: signal.close_price
        for signal in signals
        if signal.close_price is not None
    }
    summary = ledger.summary(latest_prices)
    summary["signals_loaded"] = len(signals)
    summary["signal_symbols"] = [signal.symbol for signal in signals]
    summary["model_versions"] = [signal.model_versions for signal in signals]
    print(json.dumps(_json_ready(summary), indent=2, sort_keys=True))


def _json_ready(value):
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


if __name__ == "__main__":
    main()
