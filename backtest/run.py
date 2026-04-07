from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.labels import create_target

from backtest.engine import Backtester, plot_equity_curve
from backtest.strategy_wrapper import ai_strategy

# Load data
df = get_historical_data(limit=1000)

# Prepare dataset
df = create_features(df)
df = create_target(df)

# Run backtest
bt = Backtester(df)

results = bt.run(ai_strategy)

print("===== BACKTEST RESULTS =====")
print(results)
plot_equity_curve(results)