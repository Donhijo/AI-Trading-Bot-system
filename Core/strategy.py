"""
Core/strategy.py - Trading strategy definitions and interfaces.

This module provides the base strategy interface and implementations
including AI-based, rule-based, and hybrid strategies.
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import pandas as pd

from ai.features import create_features
from ai.predict import predict_signal_with_confidence, predict_signal
from config import FEATURES

logger = logging.getLogger("bot.strategy")


class Signal(Enum):
    """Trading signal enumeration."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    """Result from strategy evaluation."""
    signal: Signal
    confidence: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    @property
    def signal_str(self) -> str:
        return self.signal.value


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    All strategies must implement the generate_signal method.
    """

    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.logger = logging.getLogger(f"bot.strategy.{name}")

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        """
        Generate trading signal from price data.

        Args:
            df: DataFrame with OHLCV and feature columns

        Returns:
            StrategyResult with signal and metadata
        """
        pass

    def validate_data(self, df: pd.DataFrame, min_rows: int = 50) -> bool:
        """
        Validate that DataFrame has sufficient data.

        Args:
            df: DataFrame to validate
            min_rows: Minimum required rows

        Returns:
            True if valid
        """
        if df is None or len(df) < min_rows:
            self.logger.warning(f"Insufficient data: {len(df) if df is not None else 0} rows")
            return False
        return True


class RuleBasedStrategy(BaseStrategy):
    """
    Classic rule-based strategy using technical indicators.

    Signals based on RSI, MACD crossover, and EMA trend filter.
    """

    def __init__(
        self,
        rsi_oversold: float = 35,
        rsi_overbought: float = 65,
        use_trend_filter: bool = True,
    ):
        super().__init__("RuleBasedStrategy")
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.use_trend_filter = use_trend_filter

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        """
        Generate signal based on rule-based logic.

        Rules:
            BUY: RSI oversold + MACD crosses up + price above EMA
            SELL: RSI overbought + MACD crosses down + price below EMA
        """
        if not self.validate_data(df, min_rows=2):
            return StrategyResult(Signal.HOLD, 0.0)

        # Ensure features exist
        if "rsi" not in df.columns:
            df = create_features(df)

        row = df.iloc[-1]
        prev = df.iloc[-2]

        rsi = row.get("rsi", 50)
        macd = row.get("macd", 0)
        prev_macd = prev.get("macd", 0)
        ema = row.get("ema", row["close"])
        close = row["close"]

        # Detect MACD crosses
        macd_crossed_up = (macd > 0) and (prev_macd <= 0)
        macd_crossed_down = (macd < 0) and (prev_macd >= 0)

        # Trend filter
        above_ema = close > ema if self.use_trend_filter else True
        below_ema = close < ema if self.use_trend_filter else True

        # Generate signals
        if rsi < self.rsi_oversold and macd_crossed_up and above_ema:
            confidence = min(0.9, (self.rsi_oversold - rsi) / self.rsi_oversold + 0.3)
            return StrategyResult(
                Signal.BUY,
                confidence,
                {"rsi": rsi, "macd": macd, "above_ema": above_ema},
            )

        if rsi > self.rsi_overbought and macd_crossed_down and below_ema:
            confidence = min(0.9, (rsi - self.rsi_overbought) / (100 - self.rsi_overbought) + 0.3)
            return StrategyResult(
                Signal.SELL,
                confidence,
                {"rsi": rsi, "macd": macd, "below_ema": below_ema},
            )

        return StrategyResult(Signal.HOLD, 0.0, {"rsi": rsi, "macd": macd})


class AIStrategy(BaseStrategy):
    """
    AI-powered strategy using the trained XGBoost model.

    Generates signals based on model predictions with confidence scores.
    """

    def __init__(self, features: list = None, confidence_threshold: float = 0.6):
        super().__init__("AIStrategy")
        self.features = features or FEATURES
        self.confidence_threshold = confidence_threshold

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        """
        Generate signal using AI model prediction.

        Args:
            df: DataFrame with price data

        Returns:
            StrategyResult with predicted signal
        """
        if not self.validate_data(df, min_rows=10):
            return StrategyResult(Signal.HOLD, 0.0)

        # Ensure features are calculated
        if "rsi" not in df.columns:
            df = create_features(df)

        # Get latest feature row
        try:
            latest = df[self.features].tail(1)
        except KeyError as e:
            self.logger.error(f"Missing features: {e}")
            return StrategyResult(Signal.HOLD, 0.0)

        # Get prediction with confidence
        try:
            signal_str, confidence = predict_signal_with_confidence(latest)
            signal = Signal(signal_str)

            # Filter by confidence threshold
            if confidence < self.confidence_threshold:
                self.logger.debug(f"Confidence {confidence:.2f} below threshold, HOLD")
                return StrategyResult(Signal.HOLD, confidence, {"reason": "low_confidence"})

            return StrategyResult(
                signal,
                confidence,
                {"features": latest.to_dict("records")[0]},
            )

        except Exception as e:
            self.logger.error(f"Prediction failed: {e}")
            return StrategyResult(Signal.HOLD, 0.0, {"error": str(e)})


class HybridStrategy(BaseStrategy):
    """
    Hybrid strategy combining AI and rule-based approaches.

    Both strategies must agree directionally for a trade signal.
    Can optionally weight the AI signal more heavily.
    """

    def __init__(
        self,
        ai_weight: float = 0.7,
        require_agreement: bool = True,
        confidence_threshold: float = 0.6,
    ):
        super().__init__("HybridStrategy")
        self.ai_strategy = AIStrategy(confidence_threshold=confidence_threshold)
        self.rule_strategy = RuleBasedStrategy()
        self.ai_weight = ai_weight
        self.require_agreement = require_agreement

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        """
        Generate signal by combining AI and rule-based strategies.

        If require_agreement is True, both must agree for a trade.
        If False, uses weighted voting.
        """
        if not self.validate_data(df, min_rows=10):
            return StrategyResult(Signal.HOLD, 0.0)

        # Get signals from both strategies
        ai_result = self.ai_strategy.generate_signal(df)
        rule_result = self.rule_strategy.generate_signal(df)

        self.logger.debug(
            f"AI: {ai_result.signal.value} ({ai_result.confidence:.2f}), "
            f"Rule: {rule_result.signal.value} ({rule_result.confidence:.2f})"
        )

        # Agreement mode - both must agree
        if self.require_agreement:
            if ai_result.signal == rule_result.signal and ai_result.signal != Signal.HOLD:
                # Both agree on a trade - combine confidence
                combined_confidence = (
                    ai_result.confidence * self.ai_weight
                    + rule_result.confidence * (1 - self.ai_weight)
                )
                return StrategyResult(
                    ai_result.signal,
                    combined_confidence,
                    {
                        "ai_signal": ai_result.signal.value,
                        "rule_signal": rule_result.signal.value,
                        "ai_confidence": ai_result.confidence,
                        "rule_confidence": rule_result.confidence,
                    },
                )
            return StrategyResult(Signal.HOLD, 0.0, {"reason": "no_agreement"})

        # Weighted voting mode
        votes = {Signal.BUY: 0.0, Signal.SELL: 0.0, Signal.HOLD: 0.0}

        votes[ai_result.signal] += ai_result.confidence * self.ai_weight
        votes[rule_result.signal] += rule_result.confidence * (1 - self.ai_weight)

        # Get winning signal
        winning_signal = max(votes, key=votes.get)
        winning_confidence = votes[winning_signal]

        if winning_signal == Signal.HOLD or winning_confidence < 0.3:
            return StrategyResult(Signal.HOLD, winning_confidence, {"votes": votes})

        return StrategyResult(
            winning_signal,
            winning_confidence,
            {
                "votes": votes,
                "ai_contrib": votes[ai_result.signal] if ai_result.signal == winning_signal else 0,
                "rule_contrib": votes[rule_result.signal] if rule_result.signal == winning_signal else 0,
            },
        )


class MultiTimeframeStrategy(BaseStrategy):
    """
    Strategy that aggregates signals across multiple timeframes.

    Requires agreement across timeframes for high-confidence signals.
    """

    def __init__(
        self,
        timeframes: list = None,
        base_strategy: str = "hybrid",
        min_agreement: int = 2,
    ):
        super().__init__("MultiTimeframeStrategy")
        self.timeframes = timeframes or ["15m", "1h", "4h"]
        self.min_agreement = min_agreement

        # Create base strategy instances
        if base_strategy == "ai":
            self.base_strategy = AIStrategy()
        elif base_strategy == "rule":
            self.base_strategy = RuleBasedStrategy()
        else:
            self.base_strategy = HybridStrategy()

    def generate_signal(self, df: pd.DataFrame) -> StrategyResult:
        """
        Generate signal based on multi-timeframe analysis.

        Note: This requires data from multiple timeframes to be available.
        For now, passes through to base strategy.
        """
        # TODO: Implement multi-timeframe data fetching and aggregation
        return self.base_strategy.generate_signal(df)


# Strategy factory
def create_strategy(strategy_type: str, **kwargs) -> BaseStrategy:
    """
    Factory function to create strategy instances.

    Args:
        strategy_type: 'ai', 'rule', 'hybrid', or 'multi'
        **kwargs: Strategy-specific parameters

    Returns:
        Strategy instance
    """
    strategies = {
        "ai": AIStrategy,
        "rule": RuleBasedStrategy,
        "hybrid": HybridStrategy,
        "multi": MultiTimeframeStrategy,
    }

    if strategy_type not in strategies:
        raise ValueError(f"Unknown strategy type: {strategy_type}")

    return strategies[strategy_type](**kwargs)
