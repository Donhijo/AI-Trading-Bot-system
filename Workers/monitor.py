"""
Workers/monitor.py - Background monitoring worker.

Provides continuous monitoring of:
- Trade execution
- Account balance
- System health
- Alerts and notifications
"""
import os
import time
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable, List, Dict, Any
from enum import Enum
import json

import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    SYMBOL,
    INITIAL_BALANCE,
)
from Database.db import get_db, log_balance_snapshot
from Services.broker import get_broker

logger = logging.getLogger("bot.monitor")


class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Alert message data."""
    level: AlertLevel
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class SystemMetrics:
    """System performance metrics."""
    timestamp: datetime
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    disk_percent: Optional[float] = None
    network_io: Optional[Dict] = None


class NotificationService:
    """
    Unified notification service supporting multiple channels.
    """

    def __init__(
        self,
        telegram_token: str = None,
        telegram_chat_id: str = None,
    ):
        self.telegram_token = telegram_token or TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = telegram_chat_id or TELEGRAM_CHAT_ID
        self.enabled = bool(self.telegram_token and self.telegram_chat_id)

        self.logger = logging.getLogger("bot.notifications")

    def send_telegram(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send notification via Telegram."""
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            success = response.status_code == 200
            if not success:
                self.logger.warning(f"Telegram send failed: {response.text}")
            return success
        except Exception as e:
            self.logger.error(f"Telegram notification failed: {e}")
            return False

    def send(self, alert: Alert):
        """Send alert through all configured channels."""
        # Format message based on level
        icons = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }

        icon = icons.get(alert.level, "📌")
        formatted = f"{icon} <b>{alert.level.value.upper()}</b>\n{alert.message}"

        # Add timestamp
        formatted += f"\n\n<em>{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</em>"

        # Send to Telegram
        self.send_telegram(formatted)

        # Also log
        log_func = {
            AlertLevel.INFO: self.logger.info,
            AlertLevel.WARNING: self.logger.warning,
            AlertLevel.ERROR: self.logger.error,
            AlertLevel.CRITICAL: self.logger.critical,
        }.get(alert.level, self.logger.info)

        log_func(f"[{alert.level.value}] {alert.message}")


class MonitoringWorker(threading.Thread):
    """
    Background worker for continuous monitoring.

    Monitors:
    - Account balance and equity
    - Open positions
    - System resources
    - Bot health status
    """

    def __init__(
        self,
        check_interval: int = 60,
        notification_service: Optional[NotificationService] = None,
        symbol: str = SYMBOL,
        initial_balance: float = INITIAL_BALANCE,
    ):
        super().__init__(name="MonitoringWorker", daemon=True)

        self.check_interval = check_interval
        self.notifications = notification_service or NotificationService()
        self.symbol = symbol
        self.initial_balance = initial_balance

        self._stop_event = threading.Event()
        self._alerts: List[Alert] = []
        self._callbacks: List[Callable] = []

        self.broker = get_broker()

        self.logger = logging.getLogger("bot.monitor")

        # Alert thresholds
        self.drawdown_warning = 0.05  # 5%
        self.drawdown_critical = 0.10  # 10%

    def stop(self):
        """Stop the monitoring worker."""
        self._stop_event.set()
        self.logger.info("Monitoring worker stopping...")

    def run(self):
        """Main monitoring loop."""
        self.logger.info("Monitoring worker started")
        self.notifications.send(
            Alert(AlertLevel.INFO, "🤖 Monitoring worker started")
        )

        while not self._stop_event.is_set():
            try:
                self._check_balance()
                self._check_system_health()

                # Sleep with interrupt handling
                self._stop_event.wait(self.check_interval)

            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
                self._add_alert(AlertLevel.ERROR, f"Monitor error: {e}")
                time.sleep(5)

        self.logger.info("Monitoring worker stopped")

    def _check_balance(self):
        """Check and log account balance."""
        try:
            balance_data = self.broker.get_account_balance("USDT")
            balance = balance_data.get("free", 0.0)

            # Calculate drawdown
            drawdown = max(0, (self.initial_balance - balance) / self.initial_balance)

            # Log to database
            log_balance_snapshot(balance, "USDT")

            # Check thresholds
            if drawdown >= self.drawdown_critical:
                self._add_alert(
                    AlertLevel.CRITICAL,
                    f"Max drawdown reached: {drawdown:.1%}",
                    {"balance": balance, "drawdown": drawdown},
                )
            elif drawdown >= self.drawdown_warning:
                self._add_alert(
                    AlertLevel.WARNING,
                    f"High drawdown: {drawdown:.1%}",
                    {"balance": balance, "drawdown": drawdown},
                )

            # Notify on significant changes (5%+)
            self.logger.debug(f"Balance check: ${balance:.2f}, Drawdown: {drawdown:.2%}")

        except Exception as e:
            self.logger.error(f"Balance check failed: {e}")

    def _check_system_health(self):
        """Check system resource usage."""
        try:
            import psutil

            metrics = SystemMetrics(
                timestamp=datetime.now(),
                cpu_percent=psutil.cpu_percent(interval=1),
                memory_percent=psutil.virtual_memory().percent,
                disk_percent=psutil.disk_usage("/").percent,
            )

            # Alert on high resource usage
            if metrics.cpu_percent > 90:
                self._add_alert(
                    AlertLevel.WARNING,
                    f"High CPU usage: {metrics.cpu_percent:.1f}%"
                )

            if metrics.memory_percent > 90:
                self._add_alert(
                    AlertLevel.WARNING,
                    f"High memory usage: {metrics.memory_percent:.1f}%"
                )

            if metrics.disk_percent > 90:
                self._add_alert(
                    AlertLevel.ERROR,
                    f"Low disk space: {metrics.disk_percent:.1f}% used"
                )

        except ImportError:
            # psutil not installed, skip system health checks
            pass
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")

    def _add_alert(self, level: AlertLevel, message: str, metadata: Dict = None):
        """Add an alert and notify if needed."""
        alert = Alert(level, message, metadata=metadata or {})
        self._alerts.append(alert)

        # Keep only last 100 alerts
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]

        # Send notification
        self.notifications.send(alert)

        # Trigger callbacks
        for callback in self._callbacks:
            try:
                callback(alert)
            except Exception as e:
                self.logger.error(f"Alert callback error: {e}")

    def get_recent_alerts(
        self,
        level: Optional[AlertLevel] = None,
        minutes: int = 60,
    ) -> List[Alert]:
        """Get recent alerts filtered by level and time."""
        cutoff = datetime.now() - timedelta(minutes=minutes)

        filtered = [
            a for a in self._alerts
            if a.timestamp >= cutoff and (level is None or a.level == level)
        ]
        return filtered

    def on_alert(self, callback: Callable):
        """Register callback for new alerts."""
        self._callbacks.append(callback)

    def get_status(self) -> Dict[str, Any]:
        """Get current monitoring status."""
        return {
            "running": self.is_alive(),
            "check_interval": self.check_interval,
            "total_alerts": len(self._alerts),
            "recent_alerts": [a.to_dict() for a in self._alerts[-10:]],
        }


class TradeMonitor:
    """
    Monitors individual trades for SL/TP hits and updates.
    """

    def __init__(self, notification_service: Optional[NotificationService] = None):
        self.notifications = notification_service or NotificationService()
        self.active_trades: Dict[str, Dict] = {}

    def register_trade(self, trade_id: str, entry_price: float, sl: float, tp: float):
        """Register a new trade for monitoring."""
        self.active_trades[trade_id] = {
            "entry_price": entry_price,
            "sl": sl,
            "tp": tp,
            "entry_time": datetime.now(),
        }

    def check_trade(self, trade_id: str, current_price: float, high: float, low: float):
        """Check if trade should exit based on SL/TP."""
        if trade_id not in self.active_trades:
            return None

        trade = self.active_trades[trade_id]

        # Check SL/TP
        if low <= trade["sl"]:
            self._notify_exit(trade_id, "stop_loss", trade["sl"])
            del self.active_trades[trade_id]
            return "stop_loss"

        if high >= trade["tp"]:
            self._notify_exit(trade_id, "take_profit", trade["tp"])
            del self.active_trades[trade_id]
            return "take_profit"

        return None

    def _notify_exit(self, trade_id: str, reason: str, price: float):
        """Send notification for trade exit."""
        self.notifications.send(
            Alert(
                AlertLevel.INFO,
                f"Trade {trade_id} exited: {reason} @ {price:.2f}",
                {"trade_id": trade_id, "exit_reason": reason, "price": price},
            )
        )


# Convenience functions
def create_monitor(
    check_interval: int = 60,
    enable_notifications: bool = True,
) -> MonitoringWorker:
    """Create and configure a monitoring worker."""
    notifications = NotificationService() if enable_notifications else None
    return MonitoringWorker(
        check_interval=check_interval,
        notification_service=notifications,
    )
