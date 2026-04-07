"""
Services module - External service integrations.

Provides service-layer abstractions for:
- Exchange connectivity (Binance)
- Data feeds (historical and real-time)
- Notifications (Telegram, Email)
- Market data providers
"""

from Services.broker import BinanceBroker, get_broker
from Services.data_feed import DataFeedService, HistoricalDataService

__all__ = [
    "BinanceBroker",
    "get_broker",
    "DataFeedService",
    "HistoricalDataService",
]
