"""Thin wrapper around alpaca-py's trading + market data clients."""
from __future__ import annotations

import logging

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

from ..config import Credentials

log = logging.getLogger(__name__)


class AlpacaBroker:
    def __init__(self, creds: Credentials) -> None:
        self.paper = creds.paper
        self.trading = TradingClient(creds.api_key, creds.secret_key, paper=creds.paper)
        self.data = StockHistoricalDataClient(creds.api_key, creds.secret_key)

    # -- account / market state ------------------------------------------
    def account(self):
        return self.trading.get_account()

    def clock(self):
        return self.trading.get_clock()

    def positions(self) -> dict[str, float]:
        return {p.symbol: float(p.qty) for p in self.trading.get_all_positions()}

    def open_order_symbols(self) -> set[str]:
        orders = self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return {o.symbol for o in orders}

    def latest_prices(self, symbols: list[str]) -> dict[str, float]:
        """Latest trade prices (IEX feed: real-time and free)."""
        try:
            trades = self.data.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=symbols, feed=DataFeed.IEX))
            return {s: float(t.price) for s, t in trades.items()}
        except Exception as exc:  # fall back to last close upstream
            log.warning("Could not fetch latest prices: %s", exc)
            return {}

    # -- orders ------------------------------------------------------------
    def submit_market(self, symbol: str, delta: int):
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        req = MarketOrderRequest(symbol=symbol, qty=abs(delta), side=side,
                                 time_in_force=TimeInForce.DAY)
        return self.trading.submit_order(req)

    def flatten(self) -> None:
        log.warning("Cancelling all orders and closing all positions")
        self.trading.close_all_positions(cancel_orders=True)
