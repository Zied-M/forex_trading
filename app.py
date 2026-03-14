import pandas as pd
from flask import Flask, request, jsonify, render_template

# Local imports
from simulator import load_data, TradingSimulator

app = Flask(__name__)

# Preload data and models
print("Loading data and models...")
DATA_PATH = "df_2024.csv"
COMBO_PATH = "simulation_combo_2024.csv"
DIR_MODEL = "dir_model_lightgbm.joblib"
VOL_MODEL = "vol_model_elasticnet.joblib"

raw_df = load_data(DATA_PATH, COMBO_PATH)
sim = TradingSimulator(DIR_MODEL, VOL_MODEL)
print("Generating predictions on the full dataset...")
predicted_df = sim.generate_predictions(raw_df)
print("Initialization complete!")

@app.route('/')
def index():
    # Pass bounds to frontend
    min_date = predicted_df['datetime'].min().strftime('%Y-%m-%dT%H:%M')
    max_date = predicted_df['datetime'].max().strftime('%Y-%m-%dT%H:%M')
    return render_template('index.html', min_date=min_date, max_date=max_date)

@app.route('/api/simulate', methods=['POST'])
def simulate():
    try:
        data = request.json
        start_date = data.get('start_date', None)
        range_hours = int(data.get('range_hours', 24*30))
        strategy = int(data.get('strategy', 1))
        capital = float(data.get('capital', 100000))
        lower = float(data.get('lower', 0.45))
        upper = float(data.get('upper', 0.55))
        vol_filter = bool(data.get('vol_filter', False))
        trade_size = float(data.get('trade_size', 100000))
        
        # Update sim params
        sim.initial_capital = capital
        sim.contract_size = trade_size
        
        # Filter dataset
        df = predicted_df.copy()
        if start_date:
            df = df[df['datetime'] >= pd.to_datetime(start_date)]
        if len(df) > range_hours:
            df = df.head(range_hours)
            
        df = df.reset_index(drop=True)
        
        if len(df) == 0:
            return jsonify({"error": "No data available for the given timeframe."}), 400
            
        if strategy == 1:
            df = sim.run_strategy_1(df)
        else:
            df = sim.run_strategy_2(df, lower_thresh=lower, upper_thresh=upper, use_vol_filter=vol_filter)
            
        summary = sim.generate_summary(df)
        
        # Prepare timeseries for JSON (replace NaNs with 0 for JSON serialization)
        df = df.fillna(0)
        
        timeseries = {
            'datetime': df['datetime'].dt.strftime('%Y-%m-%d %H:%M').tolist(),
            'equity': df['equity'].tolist(),
            'ret_fwd': df['ret_fwd'].tolist(),
            'p_up': df['p_up'].tolist(),
            'close': df['close'].tolist()
        }
        
        return jsonify({
            'summary': summary,
            'timeseries': timeseries
        })
    except Exception as e:
        print(f"Error during simulation: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
