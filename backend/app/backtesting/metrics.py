from __future__ import annotations

import math

import pandas as pd


def calculate_metrics(equity: pd.DataFrame, trades: pd.DataFrame, initial_cash: float) -> dict[str, float | int | None]:
    final_equity = float(equity.iloc[-1]["equity"])
    total_return = final_equity / initial_cash - 1.0
    days = max(1, (equity.iloc[-1]["date"] - equity.iloc[0]["date"]).days)
    years = days / 365.25
    cagr = (final_equity / initial_cash) ** (1 / years) - 1 if years > 0 and final_equity > 0 else None
    daily_returns = equity.set_index("date")["equity"].pct_change().dropna()
    daily_std = float(daily_returns.std(ddof=1)) if len(daily_returns) > 1 else 0.0
    sharpe = float(daily_returns.mean() / daily_std * math.sqrt(252)) if daily_std > 0 else None
    drawdown = equity["equity"] / equity["equity"].cummax() - 1.0
    if trades.empty:
        wins = trades
        losses = trades
        profit_factor = None
        expectancy = None
    else:
        wins = trades[trades["net_pnl"] > 0]
        losses = trades[trades["net_pnl"] < 0]
        loss_total = abs(float(losses["net_pnl"].sum()))
        profit_factor = float(wins["net_pnl"].sum()) / loss_total if loss_total > 0 else None
        expectancy = float(trades["net_pnl"].mean())
    return {
        "initial_cash": round(initial_cash, 2),
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return * 100, 4),
        "cagr_pct": round(cagr * 100, 4) if cagr is not None else None,
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 4),
        "sharpe_252": round(sharpe, 4) if sharpe is not None else None,
        "trade_count": int(len(trades)),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 4) if len(trades) else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "average_net_pnl": round(expectancy, 2) if expectancy is not None else None,
    }
