import argparse
import logging
from pathlib import Path
import pandas as pd
import numpy as np
import joblib

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_data(data_path: str, combo_path: str = None) -> pd.DataFrame:
    """Loads the dataset and aligns it with datetimes if available."""
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found at {data_path}")
    
    logging.info(f"Loading data from {data_path}")
    df = pd.read_csv(data_path)
    
    # Try to extract the datetime from the combo file if it's missing in df
    if 'datetime' not in df.columns and combo_path and Path(combo_path).exists():
        logging.info(f"Datetime column not found in {data_path}. Attempting to merge from {combo_path}")
        combo_df = pd.read_csv(combo_path)
        if len(combo_df) == len(df):
            df['datetime'] = pd.to_datetime(combo_df['datetime'])
        else:
            logging.warning(f"Length mismatch: {data_path} has {len(df)} rows, {combo_path} has {len(combo_df)}. Using sequential index for datetime.")
            df['datetime'] = pd.date_range(start='2024-01-01', periods=len(df), freq='H')
    elif 'datetime' not in df.columns:
         logging.warning(f"No datetime column found. Using sequential index.")
         df['datetime'] = pd.date_range(start='2024-01-01', periods=len(df), freq='H')
    else:
        df['datetime'] = pd.to_datetime(df['datetime'])

    df = df.sort_values('datetime').reset_index(drop=True)
    
    # Identify the target return column
    if 'y_return_1h' in df.columns:
        df['ret_fwd'] = df['y_return_1h']
    elif 'ret_fwd' not in df.columns:
        raise ValueError("Dataset must contain either 'y_return_1h' or 'ret_fwd' column for forward returns.")

    return df

class TradingSimulator:
    def __init__(self, dir_model_path, vol_model_path, initial_capital=100000.0, transaction_cost=2.0, contract_size=100000):
        self.dir_model = joblib.load(dir_model_path)
        self.vol_model = joblib.load(vol_model_path)
        
        self.initial_capital = initial_capital
        self.transaction_cost = transaction_cost # Fixed cost per trade in USD
        self.contract_size = contract_size # Assuming 1 standard lot
        
        # Get features required by models
        self.dir_features = getattr(self.dir_model, 'feature_name_', getattr(self.dir_model, 'feature_names_in_', []))
        self.vol_features = getattr(self.vol_model, 'feature_names_in_', [])
        
    def generate_predictions(self, df: pd.DataFrame):
        logging.info("Generating predictions using models...")
        
        # Ensure all required features are present
        if len(self.dir_features) > 0:
            missing_dir = [f for f in self.dir_features if f not in df.columns]
            if missing_dir:
                raise ValueError(f"Missing features for direction model: {missing_dir}")
            X_dir = df[self.dir_features]
        else:
            # Fallback if feature names aren't saved - use all columns except structural ones
            cols_to_drop = ['datetime', 'ret_fwd', 'y_return_1h', 'y_direction_1h', 'y_label_1h', 'y_vol_1h']
            X_dir = df.drop(columns=[c for c in cols_to_drop if c in df.columns])
            
        if len(self.vol_features) > 0:
            missing_vol = [f for f in self.vol_features if f not in df.columns]
            if missing_vol:
                raise ValueError(f"Missing features for volatility model: {missing_vol}")
            X_vol = df[self.vol_features]
        else:
            X_vol = df.drop(columns=[c for c in cols_to_drop if c in df.columns])

        # Predict probability of UP
        preds_proba = self.dir_model.predict_proba(X_dir)
        df['p_up'] = preds_proba[:, 1] if preds_proba.shape[1] > 1 else preds_proba
        
        # Predict volatility
        df['pred_vol'] = self.vol_model.predict(X_vol)
        
        return df

    def run_strategy_1(self, df: pd.DataFrame):
        """Strategy 1: Always-on Direction Strategy"""
        logging.info("Running Strategy 1 (Always-on Direction)")
        # +1 for Long (p_up > 0.5), -1 for Short
        df['position'] = np.where(df['p_up'] > 0.5, 1, -1)
        return self._calculate_equity(df)

    def run_strategy_2(self, df: pd.DataFrame, lower_thresh=0.45, upper_thresh=0.55, use_vol_filter=False):
        """Strategy 2: Selective Confidence Strategy"""
        logging.info(f"Running Strategy 2 (Selective Confidence) | Lower: {lower_thresh}, Upper: {upper_thresh}, Vol Filter: {use_vol_filter}")
        
        # Base signal
        conditions = [
            (df['p_up'] > upper_thresh),
            (df['p_up'] < lower_thresh)
        ]
        choices = [1, -1]
        df['position'] = np.select(conditions, choices, default=0)
        
        # Volatility filter
        if use_vol_filter:
            vol_median = df['pred_vol'].median()
            logging.info(f"Volatility median threshold: {vol_median:.6f}")
            df['position'] = np.where(df['pred_vol'] > vol_median, df['position'], 0)
            
        return self._calculate_equity(df)

    def _calculate_equity(self, df: pd.DataFrame):
        # Calculate when positions change to apply transaction costs
        # Shift position by 1 because we enter at the END of current hour, so trade cost applies then.
        df['pos_change'] = df['position'].diff().fillna(df['position']) 
        df['trades'] = np.where(df['pos_change'] != 0, 1, 0)
        
        # The position held DURING the hour earns ret_fwd
        # Wait, if ret_fwd is the return from t to t+1, and we predict at t, we take position at t, we earn ret_fwd.
        # Position is established at time t.
        df['strategy_return'] = df['position'] * df['ret_fwd']
        
        # Calculate raw profit in dollars per hour per contract
        df['gross_pnl_usd'] = df['strategy_return'] * self.contract_size
        
        # Transaction costs in USD
        df['cost_usd'] = df['trades'] * self.transaction_cost
        
        # Net PnL
        df['net_pnl_usd'] = df['gross_pnl_usd'] - df['cost_usd']
        
        # Equity curve
        df['equity'] = self.initial_capital + df['net_pnl_usd'].cumsum()
        
        return df

    def generate_summary(self, df: pd.DataFrame):
        total_trades = df['trades'].sum()
        total_gross_pnl = df['gross_pnl_usd'].sum()
        total_costs = df['cost_usd'].sum()
        total_net_pnl = df['net_pnl_usd'].sum()
        final_equity = df['equity'].iloc[-1]
        
        # Win rate (percentage of hours with positive return when positioned)
        active_hours = df[df['position'] != 0]
        win_rate = (active_hours['strategy_return'] > 0).mean() if len(active_hours) > 0 else 0
        
        summary = {
            "Initial Capital": self.initial_capital,
            "Final Equity": final_equity,
            "Total Net PnL": total_net_pnl,
            "Total Gross PnL": total_gross_pnl,
            "Total Costs": total_costs,
            "Total Trades": int(total_trades),
            "Win Rate": float(win_rate)
        }
        return summary

def main():
    parser = argparse.ArgumentParser(description="EURUSD Trading Simulator")
    parser.add_argument("--data", type=str, default="df_2024.csv", help="Dataset CSV")
    parser.add_argument("--combo", type=str, default="simulation_combo_2024.csv", help="Combo CSV for dates")
    parser.add_argument("--dir_model", type=str, default="dir_model_lightgbm.joblib", help="Direction Model")
    parser.add_argument("--vol_model", type=str, default="vol_model_elasticnet.joblib", help="Volatility Model")
    parser.add_argument("--capital", type=float, default=100000.0, help="Initial capital")
    parser.add_argument("--cost", type=float, default=2.0, help="Transaction cost per trade")
    parser.add_argument("--strategy", type=int, choices=[1, 2], default=1, help="Strategy (1 or 2)")
    
    # Strat 2 params
    parser.add_argument("--lower", type=float, default=0.45, help="Lower threshold (Strat 2)")
    parser.add_argument("--upper", type=float, default=0.55, help="Upper threshold (Strat 2)")
    parser.add_argument("--vol_filter", action="store_true", help="Enable vol filter (Strat 2)")
    
    args = parser.parse_args()
    
    try:
        df = load_data(args.data, args.combo)
        
        sim = TradingSimulator(
            dir_model_path=args.dir_model,
            vol_model_path=args.vol_model,
            initial_capital=args.capital,
            transaction_cost=args.cost
        )
        
        df = sim.generate_predictions(df)
        
        if args.strategy == 1:
            df = sim.run_strategy_1(df)
        elif args.strategy == 2:
            df = sim.run_strategy_2(df, lower_thresh=args.lower, upper_thresh=args.upper, use_vol_filter=args.vol_filter)
            
        summary = sim.generate_summary(df)
        
        print("\n=== SIMULATION SUMMARY ===")
        for k, v in summary.items():
            if isinstance(v, float):
                print(f"{k}: {v:.2f}")
            else:
                print(f"{k}: {v}")
                
        # Save output
        out_file = f"sim_results_strat{args.strategy}.csv"
        df[['datetime', 'ret_fwd', 'p_up', 'pred_vol', 'position', 'pos_change', 'gross_pnl_usd', 'cost_usd', 'net_pnl_usd', 'equity']].to_csv(out_file, index=False)
        logging.info(f"Detailed results saved to {out_file}")
        
    except Exception as e:
        logging.error(f"Simulation failed: {e}")
        raise

if __name__ == "__main__":
    main()
