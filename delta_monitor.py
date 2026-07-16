#!/usr/bin/env python3
"""
Delta Exchange Asset Monitor
Fetches OHLCV candle data from Delta Exchange V2 API and displays
a beautiful text-based candlestick chart and data table in the terminal.
Supports S&P 500, Nasdaq, Gold, Silver, Solana, XRP, and custom symbols.
"""

import sys
import os
import urllib.request
import urllib.parse
import json
import time
from datetime import datetime
import argparse
import hmac
import hashlib
import subprocess
import signal
import random

# Reconfigure stdout to use UTF-8, resolving UnicodeEncodeError on Windows terminals
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Older Python versions where reconfigure is not available
        import codecs
        try:
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        except Exception:
            pass

# Enable ANSI escape sequences on Windows console
if sys.platform == "win32":
    os.system("")

# ANSI styling helper constants
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
UNDERLINE = "\033[4m"
WHITE_BG = "\033[47m\033[30m"
DARK_GRAY = "\033[90m"

# Map of user-friendly asset names to Delta India symbols
PRECONFIGURED_ASSETS = {
    '1': {'name': 'S&P 500 Index (SPYXUSD)', 'symbol': 'SPYXUSD', 'category': 'Stock Index'},
    '2': {'name': 'Nasdaq-100 Index (QQQXUSD)', 'symbol': 'QQQXUSD', 'category': 'Stock Index'},
    '3': {'name': 'Gold (XAUTUSD)', 'symbol': 'XAUTUSD', 'category': 'Commodity'},
    '4': {'name': 'Silver (SLVONUSD)', 'symbol': 'SLVONUSD', 'category': 'Commodity'},
    '5': {'name': 'Solana (SOLUSD)', 'symbol': 'SOLUSD', 'category': 'Cryptocurrency'},
    '6': {'name': 'Ripple (XRPUSD)', 'symbol': 'XRPUSD', 'category': 'Cryptocurrency'},
}

# Resolutions supported by Delta Exchange API
SUPPORTED_RESOLUTIONS = {
    '1m': '1 Minute',
    '3m': '3 Minutes',
    '5m': '5 Minutes',
    '15m': '15 Minutes',
    '30m': '30 Minutes',
    '1h': '1 Hour',
    '2h': '2 Hours',
    '4h': '4 Hours',
    '1d': '1 Day',
    '1w': '1 Week',
}

def clear_screen():
    """Clear terminal screen."""
    if sys.stdout and hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
        os.system('cls' if os.name == 'nt' else 'clear')


def load_env():
    """Loads environment variables from .env file in the same directory."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        # Clear stale keys in memory starting with DELTA_
        for k in list(os.environ.keys()):
            if k.startswith("DELTA_"):
                os.environ.pop(k, None)
                
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        key, value = parts[0].strip(), parts[1].strip()
                        os.environ[key] = value
    # Fallbacks for backwards compatibility
    if not os.getenv("DELTA_API_KEY") and os.getenv("DELTA_API_KEY_1"):
        os.environ["DELTA_API_KEY"] = os.getenv("DELTA_API_KEY_1")
    if not os.getenv("DELTA_API_SECRET") and os.getenv("DELTA_API_SECRET_1"):
        os.environ["DELTA_API_SECRET"] = os.getenv("DELTA_API_SECRET_1")

def is_process_running(pid):
    """Checks if a process with the given PID is currently active (cross-platform)."""
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    else:
        try:
            out = subprocess.check_output(f"tasklist /FI \"PID eq {pid}\"", shell=True, stderr=subprocess.DEVNULL)
            return str(pid) in out.decode('utf-8', errors='ignore')
        except Exception:
            return False

def start_daemon(args_list):
    """Spawns the script in background mode as a detached process."""
    pid_path = "bot.pid"
    
    if os.path.exists(pid_path):
        try:
            with open(pid_path, "r") as f:
                pid = int(f.read().strip())
            if is_process_running(pid):
                print(f"{YELLOW}Error: Bot is already running in background (PID: {pid}).{RESET}")
                return
        except Exception:
            pass
            
    script_path = os.path.abspath(__file__)
    # Add internal --daemon-runner flag
    cmd = [sys.executable, "-u", script_path, "--daemon-runner"] + args_list
    
    # Filter out daemon controls to prevent loops
    cmd = [c for c in cmd if c not in ["--start", "--stop", "--status"]]
    
    # Parent writes spawn notice to log file before spawning
    try:
        with open("bot.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"\n--- Spawning background bot process at {datetime.now()} ---\n")
            log_file.write(f"Command: {cmd}\n")
    except Exception:
        pass
        
    creationflags = 0
    if os.name == 'nt':
        creationflags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
        
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True if os.name != 'nt' else False,
        start_new_session=True if os.name != 'nt' else False,
        cwd=os.path.dirname(script_path)
    )
    
    with open(pid_path, "w") as f:
        f.write(str(p.pid))
        
    print(f"{GREEN}Bot successfully started in background! PID: {p.pid}{RESET}")
    print(f"Logs are being written to: {os.path.abspath('bot.log')}")

def stop_daemon():
    """Reads bot.pid and stops the background bot process cleanly."""
    pid_path = "bot.pid"
    if not os.path.exists(pid_path):
        print(f"{YELLOW}Bot is not running in background (no bot.pid found).{RESET}")
        return
        
    try:
        with open(pid_path, "r") as f:
            pid = int(f.read().strip())
            
        print(f"Stopping bot process (PID: {pid})...")
        if is_process_running(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(5):
                    time.sleep(0.5)
                    if not is_process_running(pid):
                        break
                else:
                    print("Process still active. Force killing...")
                    if os.name == 'nt':
                        os.system(f"taskkill /F /PID {pid} >nul 2>&1")
                    else:
                        os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        else:
            print("Process was not active.")
            
        print(f"{GREEN}Bot stopped successfully.{RESET}")
    except Exception as e:
        print(f"{RED}Error stopping process: {e}{RESET}")
        
    if os.path.exists(pid_path):
        try:
            os.remove(pid_path)
        except OSError:
            pass

def check_daemon_status():
    """Checks if background bot is active and displays recent logs."""
    pid_path = "bot.pid"
    log_path = "bot.log"
    
    if not os.path.exists(pid_path):
        print(f"Status: {RED}Disconnected{RESET} (No active background bot running).")
        return
        
    try:
        with open(pid_path, "r") as f:
            pid = int(f.read().strip())
            
        if is_process_running(pid):
            print(f"Status: {GREEN}Active and Running{RESET} in background (PID: {pid}).")
            
            if os.path.exists(log_path):
                print(BOLD + CYAN + "\n--- Last 10 log entries (bot.log) ---" + RESET)
                with open(log_path, "r", encoding="utf-8") as f_log:
                    lines = f_log.readlines()
                    for line in lines[-10:]:
                        print(line, end="")
        else:
            print(f"Status: {YELLOW}Stale lock detected{RESET} (bot.pid exists but process is dead). Cleaning lock...")
            try:
                os.remove(pid_path)
            except OSError:
                pass
    except Exception as e:
        print(f"{RED}Error checking status: {e}{RESET}")

def load_optimized_settings():
    """Loads optimized settings from optimized_settings.json."""
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "optimized_settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading optimized settings: {e}")
    return {}

def save_optimized_settings(symbol, resolution, fast_period, slow_period):
    """Saves optimized settings for a symbol and resolution to optimized_settings.json."""
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "optimized_settings.json")
    settings = load_optimized_settings()
    
    key = f"{symbol}_{resolution}"
    settings[key] = {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        print(f"{GREEN}Settings saved to optimized_settings.json successfully!{RESET}")
    except Exception as e:
        print(f"{RED}Error saving optimized settings: {e}{RESET}")

def backtest_ema_crossover(candles, fast_period, slow_period, start_eval_idx=None, end_eval_idx=None):
    """
    Simulates Advanced Trend Following with:
    1. MTF Trend Filtering (Macro EMA)
    2. Fractional Kelly / Compounding Sizing
    3. Pyramiding (Scale-in on ATR moves)
    4. ATR Trailing Stops
    Supports warm up on historical data before evaluating strategy metrics.
    """
    if len(candles) < (slow_period * 4) + 5:
        return 0.0, 100.0, 0, 0.0, 0.0
        
    closes = [c['close'] for c in candles]
    fast_ema = calculate_ema(closes, fast_period)
    slow_ema = calculate_ema(closes, slow_period)
    macro_ema = calculate_ema(closes, slow_period * 4)  # MTF Filter
    atr = calculate_atr(candles, 14)
    
    if len(fast_ema) < len(closes) or fast_ema[-1] is None or macro_ema[-1] is None:
        return 0.0, 100.0, 0, 0.0, 0.0
        
    initial_equity = 10000.0
    equity = initial_equity
    equity_curve = [equity]
    
    warmup_idx = slow_period * 4
    if start_eval_idx is None:
        start_eval_idx = warmup_idx
    else:
        start_eval_idx = max(warmup_idx, start_eval_idx)
        
    if end_eval_idx is None:
        end_eval_idx = len(closes)
    else:
        end_eval_idx = min(len(closes), end_eval_idx)
        
    if start_eval_idx >= end_eval_idx:
        return 0.0, 100.0, 0, 0.0, 0.0
        
    position = 0 # 0 = flat, 1 = long, -1 = short
    trades_count = 0
    trade_returns = []
    
    # State tracking
    entry_price = 0.0
    stop_loss = 0.0
    highest_price = 0.0
    lowest_price = 0.0
    pyramid_count = 0
    avg_price = 0.0
    
    # Fractional Kelly Approximation (Fixed compounding risk)
    base_risk = 0.02 # 2% per trade, compounds with equity
    position_size_dollars = 0.0
    
    for i in range(warmup_idx, end_eval_idx):
        curr_close = closes[i]
        prev_close = closes[i-1]
        
        curr_fast = fast_ema[i]
        curr_slow = slow_ema[i]
        curr_macro = macro_ema[i]
        curr_atr = atr[i]
        
        if curr_fast is None or curr_macro is None or curr_atr == 0:
            continue
            
        # 1. Update Equity & Trailing Stops if in a position
        if position == 1:
            if i >= start_eval_idx:
                # Mark to market equity update
                bar_return = (curr_close - prev_close) / prev_close
                equity += position_size_dollars * bar_return
            
            # Trailing stop update
            if curr_close > highest_price:
                highest_price = curr_close
                new_stop = highest_price - (curr_atr * 2)
                if new_stop > stop_loss:
                    stop_loss = new_stop
                    
            # Pyramiding (Scale In)
            if curr_close > avg_price + (curr_atr * 1.5) and pyramid_count < 3:
                pyramid_count += 1
                if i >= start_eval_idx:
                    add_size = equity * (base_risk / 2) # Add half-size
                    position_size_dollars += add_size
                avg_price = (avg_price + curr_close) / 2 # simplified avg price
                
            # Exit Conditions (Stop Loss or Trend Reversal)
            if curr_close <= stop_loss or curr_fast < curr_slow:
                if i >= start_eval_idx:
                    trade_return = (curr_close - entry_price) / entry_price
                    trade_returns.append(trade_return)
                    trades_count += 1
                position = 0
                
        elif position == -1:
            if i >= start_eval_idx:
                bar_return = (prev_close - curr_close) / prev_close
                equity += position_size_dollars * bar_return
            
            if curr_close < lowest_price:
                lowest_price = curr_close
                new_stop = lowest_price + (curr_atr * 2)
                if new_stop < stop_loss:
                    stop_loss = new_stop
                    
            if curr_close < avg_price - (curr_atr * 1.5) and pyramid_count < 3:
                pyramid_count += 1
                if i >= start_eval_idx:
                    add_size = equity * (base_risk / 2)
                    position_size_dollars += add_size
                avg_price = (avg_price + curr_close) / 2
                
            if curr_close >= stop_loss or curr_fast > curr_slow:
                if i >= start_eval_idx:
                    trade_return = (entry_price - curr_close) / entry_price
                    trade_returns.append(trade_return)
                    trades_count += 1
                position = 0
                
        # 2. Entry Conditions (MTF Filtered)
        if position == 0:
            if i >= start_eval_idx:
                equity_curve.append(equity) # Only snapshot equity on flat to speed up calculation
            
            # LONG ENTRY
            if curr_fast > curr_slow and curr_close > curr_macro:
                position = 1
                entry_price = curr_close
                avg_price = curr_close
                highest_price = curr_close
                stop_loss = entry_price - (curr_atr * 2)
                if i >= start_eval_idx:
                    position_size_dollars = equity * base_risk * 10 # 10x leverage equivalent based on risk
                else:
                    position_size_dollars = 0.0
                pyramid_count = 0
                
            # SHORT ENTRY
            elif curr_fast < curr_slow and curr_close < curr_macro:
                position = -1
                entry_price = curr_close
                avg_price = curr_close
                lowest_price = curr_close
                stop_loss = entry_price + (curr_atr * 2)
                if i >= start_eval_idx:
                    position_size_dollars = equity * base_risk * 10
                else:
                    position_size_dollars = 0.0
                pyramid_count = 0
                
    net_profit_pct = ((equity - initial_equity) / initial_equity) * 100.0
    
    # Fast Drawdown Calculation
    peak = initial_equity
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100.0
        if dd > max_dd:
            max_dd = dd
            
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r <= 0]
    win_rate = len(wins) / len(trade_returns) if trade_returns else 0.0
    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))
    profit_factor = sum_wins / sum_losses if sum_losses > 0 else (sum_wins if sum_wins > 0 else 1.0)
    
    return net_profit_pct, max_dd, trades_count, win_rate, profit_factor

def get_backtest_candle_count(resolution):
    """Dynamically scale historical candle count to prevent curve-fitting."""
    res_lower = resolution.lower()
    if res_lower in ['1m', '3m', '5m']:
        return 10000
    elif res_lower in ['15m', '30m']:
        return 5000
    elif res_lower in ['1h', '2h']:
        return 3000
    elif res_lower in ['4h']:
        return 2000
    elif res_lower in ['1d']:
        return 500
    elif res_lower in ['1w']:
        return 150
    else:
        return 2000

def get_ema_ranges(resolution):
    """
    Returns optimal (Fast range, Slow range) search tuples for GA optimization.
    Slow range requires a minimum period distance from Fast EMA.
    """
    res_lower = resolution.lower()
    if res_lower in ['1m', '3m', '5m', '15m']:
        # Scalping timeframes: slow EMAs filter high-frequency noise
        return (10, 50), (50, 200)
    elif res_lower in ['30m', '1h', '2h', '4h']:
        # Balanced trend following
        return (8, 30), (30, 120)
    else:
        # Daily macro charts: faster response needed because candles are large
        return (5, 15), (15, 60)

def run_genetic_optimization(symbol, resolution, generations=15, pop_size=50, elites_count=5, mutation_rate=0.25):
    """
    Runs a Genetic Algorithm on historical candle data to find optimal EMA crossover parameters.
    """
    print(BOLD + CYAN + f"\n=== Starting Genetic Strategy Optimization for {symbol} ({resolution}) ===" + RESET)
    
    count = get_backtest_candle_count(resolution)
    print(f"Fetching historical candles for backtesting (Count: {count})...")
    candles, err = fetch_candle_data(symbol, resolution, count)
    if err or not candles or len(candles) < 40:
        print(f"{RED}Error fetching enough historical data: {err or 'insufficient candles'}{RESET}")
        return
        
    print(f"Loaded {len(candles)} historical candles.")
    run_genetic_optimization_with_params(symbol, resolution, candles, generations, pop_size, elites_count, mutation_rate)

def run_genetic_optimization_inner(candles, resolution, generations, pop_size, elites_count, mutation_rate):
    """
    Inner GA worker function that backtests strategies without API calls.
    Now implements Out-of-Sample (OOS) 70/30 Holdout Validation.
    """
    split_idx = int(len(candles) * 0.7)
    
    fast_range, slow_range = get_ema_ranges(resolution)
    
    population = []
    while len(population) < pop_size:
        fast = random.randint(fast_range[0], fast_range[1])
        slow = random.randint(max(slow_range[0], fast + 10), slow_range[1])
        population.append((fast, slow))
        
    best_global_fit = -9999.0
    stagnant_gens = 0
    tourn_size = max(3, pop_size // 10)
    
    # --- In-Sample Evolution (Training) ---
    for gen in range(1, generations + 1):
        scored_pop = []
        for fast, slow in population:
            profit, max_dd, trades, win_rate, profit_factor = backtest_ema_crossover(candles, fast, slow, end_eval_idx=split_idx)
            # Sharpe-like expectancy fitness formula
            fitness = profit * (1.0 + win_rate) * min(3.0, profit_factor) - (max_dd * 0.75)
            if trades < 10: # Lowered to 10 because it's only 70% of the data
                fitness -= 200.0
            scored_pop.append((fitness, (fast, slow), profit, max_dd, trades))
            
        scored_pop.sort(key=lambda x: x[0], reverse=True)
        best_fit = scored_pop[0][0]
        
        if best_fit > best_global_fit + 0.01:
            best_global_fit = best_fit
            stagnant_gens = 0
        else:
            stagnant_gens += 1
            if stagnant_gens >= 5 and gen > generations // 2:
                break
        
        # Next generation
        next_pop = [pair for fit, pair, p, dd, tr in scored_pop[:elites_count]]
        current_mut_rate = mutation_rate * (1.0 - (gen / generations) * 0.5)
        
        while len(next_pop) < pop_size:
            parents = []
            for _ in range(2):
                candidates = random.sample(scored_pop, tourn_size)
                candidates.sort(key=lambda x: x[0], reverse=True)
                parents.append(candidates[0][1])
                
            p1, p2 = parents[0], parents[1]
            
            # Blend Crossover
            child_fast = int((p1[0] + p2[0]) / 2) + random.choice([-1, 0, 1])
            child_slow = int((p1[1] + p2[1]) / 2) + random.choice([-2, 0, 2])
            
            if child_slow < child_fast + 10:
                child_slow = child_fast + 10
                
            if random.random() < current_mut_rate:
                child_fast += random.choice([-2, -1, 1, 2])
                
            if random.random() < current_mut_rate:
                child_slow += random.choice([-5, -2, 2, 5])
                
            child_fast = max(fast_range[0], min(fast_range[1], child_fast))
            child_slow = max(max(slow_range[0], child_fast + 10), min(slow_range[1], child_slow))
            next_pop.append((child_fast, child_slow))
            
        population = next_pop
        
    # --- Out-of-Sample Validation (Testing) ---
    final_scored = []
    for fast, slow in population:
        tr_p, tr_dd, tr_tr, tr_wr, tr_pf = backtest_ema_crossover(candles, fast, slow, end_eval_idx=split_idx)
        train_fitness = tr_p * (1.0 + tr_wr) * min(3.0, tr_pf) - (tr_dd * 0.75)
        if tr_tr < 10:
            train_fitness -= 200.0
            
        te_p, te_dd, te_tr, te_wr, te_pf = backtest_ema_crossover(candles, fast, slow, start_eval_idx=split_idx)
        test_fitness = te_p * (1.0 + te_wr) * min(3.0, te_pf) - (te_dd * 0.75)
        
        # Penalize if OOS performance crashes (curve-fitting detection)
        if te_p <= 0 or test_fitness < (train_fitness * 0.2):
            final_fit = train_fitness - 1000.0 
        else:
            final_fit = (train_fitness * 0.6) + (test_fitness * 0.4)
            
        final_scored.append((final_fit, (fast, slow), tr_p, tr_dd, tr_tr, te_p, te_dd, te_tr))
        
    final_scored.sort(key=lambda x: x[0], reverse=True)
    best_fitness, (best_fast, best_slow), tr_p, tr_dd, tr_tr, te_p, te_dd, te_tr = final_scored[0]
    
    # Return blended metrics for the overall fitness perspective
    blended_profit = (tr_p * 0.7) + (te_p * 0.3)
    blended_dd = max(tr_dd, te_dd)
    blended_trades = tr_tr + te_tr
    return best_fast, best_slow, blended_profit, blended_dd, blended_trades

def run_genetic_optimization_with_params(symbol, resolution, candles, generations, pop_size, elites_count, mutation_rate):
    """
    Runs final strategy optimization with custom parameters and saves settings.
    Now uses 70/30 Out-of-Sample Holdout testing to prove edge.
    """
    split_idx = int(len(candles) * 0.7)
    train_count = split_idx

    fast_range, slow_range = get_ema_ranges(resolution)

    population = []
    while len(population) < pop_size:
        fast = random.randint(fast_range[0], fast_range[1])
        slow = random.randint(max(slow_range[0], fast + 10), slow_range[1])
        population.append((fast, slow))
        
    best_global_fit = -9999.0
    stagnant_gens = 0
    tourn_size = max(3, pop_size // 10)
    
    print(f"Evolving populations over {generations} generations (Training on {train_count} candles)...")
    for gen in range(1, generations + 1):
        scored_pop = []
        for fast, slow in population:
            profit, max_dd, trades, win_rate, profit_factor = backtest_ema_crossover(candles, fast, slow, end_eval_idx=split_idx)
            fitness = profit * (1.0 + win_rate) * min(3.0, profit_factor) - (max_dd * 0.75)
            if trades < 10:
                fitness -= 200.0
            scored_pop.append((fitness, (fast, slow), profit, max_dd, trades))
            
        scored_pop.sort(key=lambda x: x[0], reverse=True)
        best_fit, best_pair, best_p, best_dd, best_tr = scored_pop[0]
        
        print(f"  Gen {gen:2d}/{generations:2d} | Best EMA: Fast {best_pair[0]:2d}/Slow {best_pair[1]:3d} | "
              f"Train Return: {best_p:+.2f}% | Max DD: {best_dd:.2f}% | Trades: {best_tr}")
              
        if best_fit > best_global_fit + 0.01:
            best_global_fit = best_fit
            stagnant_gens = 0
        else:
            stagnant_gens += 1
            if stagnant_gens >= 5 and gen > generations // 2:
                print(f"  {YELLOW}Early stopping triggered (No improvement for 5 generations){RESET}")
                break
              
        next_pop = [pair for fit, pair, p, dd, tr in scored_pop[:elites_count]]
        current_mut_rate = mutation_rate * (1.0 - (gen / generations) * 0.5)
        
        while len(next_pop) < pop_size:
            parents = []
            for _ in range(2):
                candidates = random.sample(scored_pop, tourn_size)
                candidates.sort(key=lambda x: x[0], reverse=True)
                parents.append(candidates[0][1])
                
            p1, p2 = parents[0], parents[1]
            
            child_fast = int((p1[0] + p2[0]) / 2) + random.choice([-1, 0, 1])
            child_slow = int((p1[1] + p2[1]) / 2) + random.choice([-2, 0, 2])
            
            if child_slow < child_fast + 10:
                child_slow = child_fast + 10
                
            if random.random() < current_mut_rate:
                child_fast += random.choice([-2, -1, 1, 2])
                
            if random.random() < current_mut_rate:
                child_slow += random.choice([-5, -2, 2, 5])
                
            child_fast = max(fast_range[0], min(fast_range[1], child_fast))
            child_slow = max(max(slow_range[0], child_fast + 10), min(slow_range[1], child_slow))
            next_pop.append((child_fast, child_slow))
            
        population = next_pop
        
    print(BOLD + CYAN + f"\nRunning Out-of-Sample (OOS) Validation on {len(candles) - split_idx} unseen candles..." + RESET)
    final_scored = []
    for fast, slow in population:
        tr_p, tr_dd, tr_tr, tr_wr, tr_pf = backtest_ema_crossover(candles, fast, slow, end_eval_idx=split_idx)
        train_fitness = tr_p * (1.0 + tr_wr) * min(3.0, tr_pf) - (tr_dd * 0.75)
        if tr_tr < 10:
            train_fitness -= 200.0
            
        te_p, te_dd, te_tr, te_wr, te_pf = backtest_ema_crossover(candles, fast, slow, start_eval_idx=split_idx)
        test_fitness = te_p * (1.0 + te_wr) * min(3.0, te_pf) - (te_dd * 0.75)
        
        if te_p <= 0 or test_fitness < (train_fitness * 0.2):
            final_fit = train_fitness - 1000.0
        else:
            final_fit = (train_fitness * 0.6) + (test_fitness * 0.4)
            
        final_scored.append((final_fit, (fast, slow), tr_p, tr_dd, tr_tr, te_p, te_dd, te_tr))
        
    final_scored.sort(key=lambda x: x[0], reverse=True)
    best_fitness, (best_fast, best_slow), tr_p, tr_dd, tr_tr, te_p, te_dd, te_tr = final_scored[0]
    
    print(BOLD + GREEN + f"\nOptimization Complete!" + RESET)
    print(f"Optimal EMA Strategy: Fast {best_fast} / Slow {best_slow}")
    print(f"Training (In-Sample) Return:   {tr_p:+.2f}% | Max DD: {tr_dd:.2f}% | Trades: {tr_tr}")
    
    if te_p > 0:
        print(f"Testing (Out-of-Sample) Return: {BOLD}{GREEN}{te_p:+.2f}%{RESET} | Max DD: {te_dd:.2f}% | Trades: {te_tr}")
    else:
        print(f"Testing (Out-of-Sample) Return: {BOLD}{RED}{te_p:+.2f}% (FAILED OOS){RESET} | Max DD: {te_dd:.2f}% | Trades: {te_tr}")
        
    save_optimized_settings(symbol, resolution, best_fast, best_slow)

def run_meta_genetic_optimization(symbol, resolution, meta_generations=5, meta_pop_size=10):
    """
    Runs a Meta-Genetic Algorithm to optimize the hyperparameters of the strategy optimizer.
    """
    print(BOLD + MAGENTA + f"\n=== Starting META Genetic Algorithm Hyperparameter Tuning for {symbol} ({resolution}) ===" + RESET)
    
    count = get_backtest_candle_count(resolution)
    print(f"Fetching historical candles for meta-optimization (Count: {count})...")
    candles, err = fetch_candle_data(symbol, resolution, count)
    if err or not candles or len(candles) < 40:
        print(f"{RED}Error fetching enough historical data for meta-opt: {err or 'insufficient candles'}{RESET}")
        return
        
    print(f"Loaded {len(candles)} historical candles. Initializing meta-population...")
    
    population = []
    while len(population) < meta_pop_size:
        pop_size = random.randint(15, 50)
        elites = random.randint(2, min(8, pop_size - 5))
        mut_rate = round(random.uniform(0.1, 0.4), 2)
        gens = random.randint(5, 15)
        population.append((pop_size, elites, mut_rate, gens))
        
    best_global_fit = -9999.0
    stagnant_gens = 0
    tourn_size = max(3, meta_pop_size // 4)
    
    print("Evolving GA hyperparameters...")
    for gen in range(1, meta_generations + 1):
        scored_pop = []
        for pop_size, elites, mut_rate, gens in population:
            runs_fitness = []
            for _ in range(2):
                best_fast, best_slow, profit, max_dd, trades = run_genetic_optimization_inner(
                    candles, resolution, gens, pop_size, elites, mut_rate
                )
                # Compute strategy fitness using same advanced formula
                _, _, _, win_rate, profit_factor = backtest_ema_crossover(candles, best_fast, best_slow)
                fitness = profit * (1.0 + win_rate) * min(3.0, profit_factor) - (max_dd * 0.75)
                if trades < 15:
                    fitness -= 200.0
                runs_fitness.append(fitness)
            avg_fitness = sum(runs_fitness) / len(runs_fitness)
            # Efficiency Penalty: penalize excessively large computational load
            efficiency_penalty = (pop_size * gens) * 0.05
            penalized_fitness = avg_fitness - efficiency_penalty
            scored_pop.append((penalized_fitness, (pop_size, elites, mut_rate, gens), avg_fitness))
            
        scored_pop.sort(key=lambda x: x[0], reverse=True)
        best_penalized_fit, best_params, best_real_fit = scored_pop[0]
        
        print(f"  Meta-Gen {gen:2d}/{meta_generations:2d} | Best GA Config: Pop {best_params[0]:2d}, Elites {best_params[1]:2d}, Mut {best_params[2]:.2f}, Gens {best_params[3]:2d} | Est. Avg Strategy Fitness: {best_real_fit:+.2f}")
        
        if best_penalized_fit > best_global_fit + 0.1:
            best_global_fit = best_penalized_fit
            stagnant_gens = 0
        else:
            stagnant_gens += 1
            if stagnant_gens >= 3 and gen > meta_generations // 2:
                print(f"  {YELLOW}Meta-GA Early stopping triggered (No improvement for 3 generations){RESET}")
                break
        
        # Mating and breeding
        elites_count = max(2, meta_pop_size // 4)
        next_pop = [params for pfit, params, rfit in scored_pop[:elites_count]]
        current_mut_rate = 0.25 * (1.0 - (gen / meta_generations) * 0.5)
        
        while len(next_pop) < meta_pop_size:
            parents = random.sample(scored_pop[:max(3, tourn_size)], 2)
            p1, p2 = parents[0][1], parents[1][1]
            
            # Blend Crossover
            child_pop_size = int((p1[0] + p2[0]) / 2) + random.choice([-2, 0, 2])
            child_elites = int((p1[1] + p2[1]) / 2) + random.choice([-1, 0, 1])
            child_mut_rate = round((p1[2] + p2[2]) / 2 + random.choice([-0.05, 0.0, 0.05]), 2)
            child_gens = int((p1[3] + p2[3]) / 2) + random.choice([-1, 0, 1])
            
            if child_elites >= child_pop_size:
                child_elites = max(2, child_pop_size // 5)
                
            # Mutation
            if random.random() < current_mut_rate:
                child_pop_size = max(10, min(60, child_pop_size + random.choice([-5, -2, 2, 5])))
            if random.random() < current_mut_rate:
                child_elites = max(1, min(12, child_elites + random.choice([-1, 1])))
            if random.random() < current_mut_rate:
                child_mut_rate = max(0.05, min(0.5, round(child_mut_rate + random.choice([-0.05, 0.05]), 2)))
            if random.random() < current_mut_rate:
                child_gens = max(3, min(25, child_gens + random.choice([-2, -1, 1, 2])))
                
            if child_elites >= child_pop_size:
                child_elites = max(1, child_pop_size // 5)
                
            next_pop.append((child_pop_size, child_elites, child_mut_rate, child_gens))
            
        population = next_pop
        
    final_scored = []
    for pop_size, elites, mut_rate, gens in population:
        runs_fitness = []
        for _ in range(2):
            best_fast, best_slow, profit, max_dd, trades = run_genetic_optimization_inner(
                candles, resolution, gens, pop_size, elites, mut_rate
            )
            _, _, _, win_rate, profit_factor = backtest_ema_crossover(candles, best_fast, best_slow)
            fitness = profit * (1.0 + win_rate) * min(3.0, profit_factor) - (max_dd * 0.75)
            if trades < 15:
                fitness -= 200.0
            runs_fitness.append(fitness)
        avg_fitness = sum(runs_fitness) / len(runs_fitness)
        efficiency_penalty = (pop_size * gens) * 0.05
        penalized_fitness = avg_fitness - efficiency_penalty
        final_scored.append((penalized_fitness, (pop_size, elites, mut_rate, gens), avg_fitness))
        
    final_scored.sort(key=lambda x: x[0], reverse=True)
    best_penalized_fit, (best_pop_size, best_elites, best_mut_rate, best_gens), best_avg_fit = final_scored[0]
    
    print(BOLD + GREEN + f"\nMeta-Optimization Complete!" + RESET)
    print(f"Optimal GA Configuration:")
    print(f"  Population Size: {best_pop_size}")
    print(f"  Elites Count:    {best_elites}")
    print(f"  Mutation Rate:   {best_mut_rate}")
    print(f"  Generations:     {best_gens}")
    print(f"  Expected Avg Strategy Fitness: {best_avg_fit:+.2f} (Penalized: {best_penalized_fit:+.2f})")
    
    print(BOLD + CYAN + f"\nRunning final strategy optimization using tuned hyperparameters..." + RESET)
    run_genetic_optimization_with_params(symbol, resolution, candles, best_gens, best_pop_size, best_elites, best_mut_rate)


def run_autopilot_setup(resolution='1h', generations=10):
    """
    Hands-off auto-pilot orchestration:
    1. Selects top crypto pairs.
    2. Runs Genetic Optimization on them.
    3. Restarts the background daemon tracking the optimized assets.
    """
    clear_screen()
    print(BOLD + MAGENTA + "┌" + "─"*60 + "┐" + RESET)
    print(BOLD + MAGENTA + "│" + " FULLY AUTONOMOUS AUTO-PILOT ORCHESTRATION ".center(60) + "│" + RESET)
    print(BOLD + MAGENTA + "└" + "─"*60 + "┘" + RESET)
    
    # 1. Filter for 24/7 crypto assets from preconfigured
    target_symbols = []
    for k, v in PRECONFIGURED_ASSETS.items():
        if v['category'] == 'Cryptocurrency':
            target_symbols.append(v['symbol'])
            
    print(f"\n{CYAN}[Auto-Pilot] Step 1: Target Assets Identified: {', '.join(target_symbols)}{RESET}")
    time.sleep(2)
    
    # 2. Iterate and optimize
    for sym in target_symbols:
        print(f"\n{CYAN}[Auto-Pilot] Step 2: Optimizing Strategy for {sym} on {resolution}...{RESET}")
        run_genetic_optimization(sym, resolution, generations)
        time.sleep(1)
        
    # 3. Stop existing daemon
    print(f"\n{CYAN}[Auto-Pilot] Step 3: Orchestrating Background Daemon...{RESET}")
    stop_daemon()
    time.sleep(1)
    
    # 4. Build new args and spawn
    daemon_args = [
        "--symbol", ",".join(target_symbols),
        "--resolution", resolution,
        "--monitor",
        "--poll-interval", "15"
    ]
    
    api_active = bool(os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY") or os.getenv("DELTA_API_KEY_3"))
    if api_active:
        daemon_args += ["--trade", "--trade-size", "1"]
        print(f"{YELLOW}[Auto-Pilot] Trading API credentials found. Enabling autonomous crossover trading!{RESET}")
        
    start_daemon(daemon_args)
    print(BOLD + GREEN + "\n[Auto-Pilot] Orchestration Complete! The Auto-Pilot daemon is now active." + RESET)

def save_env_keys(account_idx, key, secret, name=None):
    """Saves API credentials for a specific account index to the .env file."""
    lines = []
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    env_dict = {}
    for line in lines:
        line_s = line.strip()
        if line_s and not line_s.startswith("#"):
            parts = line_s.split("=", 1)
            if len(parts) == 2:
                env_dict[parts[0].strip()] = parts[1].strip()
                
    env_dict[f"DELTA_API_KEY_{account_idx}"] = key
    env_dict[f"DELTA_API_SECRET_{account_idx}"] = secret
    if name:
        env_dict[f"DELTA_ACCOUNT_NAME_{account_idx}"] = name
    else:
        if account_idx == 1:
            env_dict[f"DELTA_ACCOUNT_NAME_{account_idx}"] = "LONG_Account"
        elif account_idx == 2:
            env_dict[f"DELTA_ACCOUNT_NAME_{account_idx}"] = "SHORT_Account"
        else:
            env_dict[f"DELTA_ACCOUNT_NAME_{account_idx}"] = "BOTH_Account"
        
    if account_idx == 1:
        env_dict["DELTA_API_KEY"] = key
        env_dict["DELTA_API_SECRET"] = secret
        
    with open(env_path, "w", encoding="utf-8") as f_env:
        for k, v in env_dict.items():
            f_env.write(f"{k}={v}\n")

def remove_env_keys(account_idx):
    """Removes API credentials for a specific account index from the .env file."""
    lines = []
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    env_dict = {}
    for line in lines:
        line_s = line.strip()
        if line_s and not line_s.startswith("#"):
            parts = line_s.split("=", 1)
            if len(parts) == 2:
                env_dict[parts[0].strip()] = parts[1].strip()
                
    env_dict.pop(f"DELTA_API_KEY_{account_idx}", None)
    env_dict.pop(f"DELTA_API_SECRET_{account_idx}", None)
    env_dict.pop(f"DELTA_ACCOUNT_NAME_{account_idx}", None)
    
    if account_idx == 1:
        env_dict.pop("DELTA_API_KEY", None)
        env_dict.pop("DELTA_API_SECRET", None)
        
    if env_dict:
        with open(env_path, "w", encoding="utf-8") as f_env:
            for k, v in env_dict.items():
                f_env.write(f"{k}={v}\n")
    else:
        if os.path.exists(env_path):
            os.remove(env_path)

def generate_signature(secret, message):
    """Generates hex signature for API requests using HMAC-SHA256."""
    message_bytes = bytes(message, 'utf-8')
    secret_bytes = bytes(secret, 'utf-8')
    h = hmac.new(secret_bytes, message_bytes, hashlib.sha256)
    return h.hexdigest()

def make_authenticated_request(method, path, query_params=None, payload=None, account_idx=1):
    """
    Makes a signed, authenticated request to Delta Exchange API.
    Supports routing to Account 1 or Account 2 by account_idx.
    """
    if account_idx == 3:
        api_key = os.getenv("DELTA_API_KEY_3")
        api_secret = os.getenv("DELTA_API_SECRET_3")
    elif account_idx == 2:
        api_key = os.getenv("DELTA_API_KEY_2")
        api_secret = os.getenv("DELTA_API_SECRET_2")
    else:
        api_key = os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY")
        api_secret = os.getenv("DELTA_API_SECRET_1") or os.getenv("DELTA_API_SECRET")
    
    if not api_key or not api_secret:
        return None, f"API credentials for Account {account_idx} not configured."
        
    timestamp = str(int(time.time()))
    
    # query_string sorting and encoding
    query_string = ""
    if query_params:
        query_string = urllib.parse.urlencode(sorted(query_params.items()))
        
    # payload serialization
    payload_str = ""
    if payload:
        payload_str = json.dumps(payload)
        
    # Prehash: method + timestamp + path + query_string + payload
    signature_data = method.upper() + timestamp + path + query_string + payload_str
    signature = generate_signature(api_secret, signature_data)
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'api-key': api_key,
        'signature': signature,
        'timestamp': timestamp,
        'User-Agent': 'DeltaMonitor/1.0'
    }
    
    url = f"https://api.india.delta.exchange{path}"
    if query_string:
        url += f"?{query_string}"
        
    req = urllib.request.Request(
        url, 
        data=payload_str.encode('utf-8') if payload_str else None,
        headers=headers,
        method=method.upper()
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                if data.get('success'):
                    return data.get('result'), None
                else:
                    return None, f"API Error: {data.get('error', {}).get('message', 'Unknown error')}"
            else:
                return None, f"HTTP Error {response.status}"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            reset_ms = e.headers.get('X-RATE-LIMIT-RESET')
            if reset_ms:
                reset_sec = float(reset_ms) / 1000.0
                sleep_dur = min(300.0, reset_sec)
                print(f"\n{YELLOW}[Rate Limit] Exceeded (HTTP 429). Auto-sleeping for {sleep_dur:.2f}s before retrying...{RESET}")
                time.sleep(sleep_dur)
                
                # Regenerate timestamp and signature for retry
                timestamp = str(int(time.time()))
                signature_data = method.upper() + timestamp + path + query_string + payload_str
                signature = generate_signature(api_secret, signature_data)
                
                headers['timestamp'] = timestamp
                headers['signature'] = signature
                
                req_retry = urllib.request.Request(
                    url, 
                    data=payload_str.encode('utf-8') if payload_str else None,
                    headers=headers,
                    method=method.upper()
                )
                try:
                    with urllib.request.urlopen(req_retry, timeout=10) as response:
                        if response.status == 200:
                            data = json.loads(response.read().decode('utf-8'))
                            if data.get('success'):
                                return data.get('result'), None
                            else:
                                return None, f"API Error on retry: {data.get('error', {}).get('message', 'Unknown error')}"
                except Exception as retry_err:
                    return None, f"Failed on rate limit retry: {str(retry_err)}"
            return None, "API Rate Limit Exceeded (HTTP 429)."
        try:
            err_data = json.loads(e.read().decode('utf-8'))
            err_msg = err_data.get('error', {}).get('message') or err_data.get('error', {}).get('code') or e.reason
            return None, f"API Error: {err_msg}"
        except Exception:
            return None, f"HTTP Error {e.code}: {e.reason}"
    except Exception as e:
        return None, f"Connection error: {str(e)}"

def fetch_and_show_account():
    """
    Fetches open positions and wallet balances, displaying them in formatted tables for all connected accounts.
    """
    clear_screen()
    print(BOLD + CYAN + "┌" + "─"*68 + "┐" + RESET)
    print(BOLD + CYAN + "│" + f" DELTA EXCHANGE PRIVATE ACCOUNT PORTFOLIO ".center(68) + "│" + RESET)
    print(BOLD + CYAN + "└" + "─"*68 + "┘" + RESET)
    
    # Check which accounts are configured
    acc1_configured = bool(os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY"))
    acc2_configured = bool(os.getenv("DELTA_API_KEY_2"))
    acc3_configured = bool(os.getenv("DELTA_API_KEY_3"))
    
    accounts_to_check = []
    if acc1_configured:
        accounts_to_check.append((1, os.getenv("DELTA_ACCOUNT_NAME_1") or "Account 1 (Main/LONG)"))
    if acc2_configured:
        accounts_to_check.append((2, os.getenv("DELTA_ACCOUNT_NAME_2") or "Account 2 (Sub/SHORT)"))
    if acc3_configured:
        accounts_to_check.append((3, os.getenv("DELTA_ACCOUNT_NAME_3") or "Account 3 (Both LONG/SHORT)"))
        
    if not accounts_to_check:
        print(f"  {RED}No API credentials configured. Please configure in Settings (Option 10).{RESET}\n")
        return
        
    for idx, name in accounts_to_check:
        print(BOLD + GREEN + f"=================== PROFILE: {name} ===================" + RESET)
        
        # 1. Balances
        print(BOLD + MAGENTA + "--- Wallet Balances ---" + RESET)
        balances, err = make_authenticated_request("GET", "/v2/wallet/balances", account_idx=idx)
        if err:
            print(f"  {RED}Error fetching balances: {err}{RESET}\n")
        elif not balances:
            print("  No wallets or balances found.\n")
        else:
            balance_header = f" {'Asset':<10} │ {'Balance':<15} │ {'Available Balance':<20} │ {'Position Margin':<18}"
            print(BOLD + balance_header + RESET)
            print("─" * (len(balance_header) + 1))
            found_non_zero = False
            for bal in balances:
                balance_val = float(bal.get('balance', 0))
                if balance_val > 0.0001:
                    found_non_zero = True
                    print(f" {bal.get('asset_symbol', 'N/A'):<10} │ "
                          f"{balance_val:<15.4f} │ "
                          f"{float(bal.get('available_balance', 0)):<20.4f} │ "
                          f"{float(bal.get('position_margin', 0)):<18.4f}")
            if not found_non_zero:
                print("  All wallets have zero or negligible balances.")
            print()
            
        # 2. Positions
        print(BOLD + MAGENTA + "--- Open Positions ---" + RESET)
        positions, err = make_authenticated_request("GET", "/v2/positions", account_idx=idx)
        if err:
            print(f"  {RED}Error fetching positions: {err}{RESET}\n")
        else:
            active_positions = [pos for pos in positions if int(pos.get('size', 0)) != 0] if positions else []
            if not active_positions:
                print("  No active open positions.\n")
            else:
                pos_header = f" {'Symbol':<12} │ {'Direction':<10} │ {'Size':<10} │ {'Entry Price':<14} │ {'Realized P&L':<14}"
                print(BOLD + pos_header + RESET)
                print("─" * (len(pos_header) + 1))
                for pos in active_positions:
                    size = int(pos.get('size', 0))
                    direction = f"{GREEN}LONG{RESET}" if size > 0 else f"{RED}SHORT{RESET}"
                    pnl = float(pos.get('realized_pnl', 0))
                    pnl_color = GREEN if pnl >= 0 else RED
                    pnl_sign = "+" if pnl >= 0 else ""
                    
                    print(f" {pos.get('product_symbol', 'N/A'):<12} │ "
                          f"{direction:<19} │ "
                          f"{abs(size):<10} │ "
                          f"{float(pos.get('entry_price', 0)):<14.4f} │ "
                          f"{pnl_color}{pnl_sign}{pnl:<14.4f}{RESET}")
                print()

PRODUCT_ID_CACHE = {}

def get_product_id_by_symbol(symbol):
    """Fetches the product ID of a given symbol from /v2/products API."""
    if symbol in PRODUCT_ID_CACHE:
        return PRODUCT_ID_CACHE[symbol]
        
    try:
        url = "https://api.india.delta.exchange/v2/products"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                if data.get('success'):
                    products = data.get('result', [])
                    for p in products:
                        sym = p.get('symbol')
                        if sym:
                            PRODUCT_ID_CACHE[sym] = p.get('id')
                    if symbol in PRODUCT_ID_CACHE:
                        return PRODUCT_ID_CACHE[symbol]
    except Exception as e:
        print(f"Error resolving product ID for {symbol}: {e}")
        
    return None

def place_market_order(symbol, side, size, account_idx=1):
    """
    Places a Market Order on Delta Exchange for a specific account.
    """
    prod_id = get_product_id_by_symbol(symbol)
    if not prod_id:
        return None, f"Could not resolve product ID for symbol: {symbol}"
        
    payload = {
        "product_id": prod_id,
        "size": max(1, int(size)),
        "side": side.lower(),
        "order_type": "market_order"
    }
    
    result, err = make_authenticated_request("POST", "/v2/orders", payload=payload, account_idx=account_idx)
    if err:
        return None, err
        
    return result, None

def close_position_if_any(symbol, account_idx=1):
    """
    Checks if there is an active open position for the symbol on the account.
    If so, places a market order in the opposite direction to close it.
    """
    positions, err = make_authenticated_request("GET", "/v2/positions", account_idx=account_idx)
    if err or not positions:
        return None, f"No positions fetched or error: {err}"
        
    for pos in positions:
        if pos.get('product_symbol') == symbol:
            size = int(pos.get('size', 0))
            if size != 0:
                side = "sell" if size > 0 else "buy"
                print(f"Closing existing position for {symbol} on Account {account_idx} (Size: {abs(size)}, Side: {side})...")
                res, place_err = place_market_order(symbol, side, abs(size), account_idx=account_idx)
                return res, place_err
                
    return None, None

def resolution_to_seconds(res):
    """Convert resolution string (e.g. '1d', '1h', '15m') to seconds."""
    try:
        num = int(''.join(filter(str.isdigit, res)))
        unit = ''.join(filter(str.isalpha, res)).lower()
        if unit == 'm':
            return num * 60
        elif unit == 'h':
            return num * 3600
        elif unit == 'd':
            return num * 24 * 3600
        elif unit == 'w':
            return num * 7 * 24 * 3600
        else:
            return 3600
    except Exception:
        return 3600

def parse_resolution_input(user_input, default_val='1d'):
    """
    Cleans and parses resolution input. Strips quotes and allows both
    digit choices (e.g. '5') and direct codes (e.g. '1h').
    """
    cleaned = user_input.replace("'", "").replace('"', '').strip().lower()
    sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
    
    for res in sorted_resolutions:
        if cleaned == res.lower():
            return res
            
    if cleaned.isdigit():
        idx = int(cleaned) - 1
        if 0 <= idx < len(sorted_resolutions):
            return sorted_resolutions[idx]
            
    return default_val

def get_validated_int_input(prompt, help_text, default_val, min_val, max_val):
    """
    Displays user-friendly help text, checks input limits,
    and returns a validated integer with warnings on out-of-bounds inputs.
    """
    print(f"\n{YELLOW}[Help: {help_text}]{RESET}")
    while True:
        user_in = input(BOLD + prompt + RESET).strip()
        if not user_in:
            return default_val
        try:
            val = int(user_in)
            if min_val <= val <= max_val:
                return val
            else:
                print(f"{RED}[Warning: Input out of bounds! Must be between {min_val} and {max_val}.]{RESET}")
        except ValueError:
            print(f"{RED}[Warning: Invalid input! Please enter a whole number.]{RESET}")

def fetch_candle_data(symbol, resolution, candle_count):
    """
    Fetches candle data from the Delta Exchange API.
    Uses a 2.5x time buffer to account for weekends and holidays in stock/commodity data.
    If the request fails or returns empty (e.g. because start time is too far in the past),
    it dynamically retries with smaller candle counts.
    """
    attempts = [candle_count, candle_count // 2, candle_count // 4, 1000, 500, 200]
    last_err = "No data"
    
    for count in attempts:
        if count < 2:
            continue
            
        seconds_needed = int(count * 2.5 * resolution_to_seconds(resolution))
        end_time = int(time.time())
        start_time = end_time - seconds_needed

        params = {
            'symbol': symbol,
            'resolution': resolution,
            'start': start_time,
            'end': end_time
        }

        query = urllib.parse.urlencode(params)
        url = f"https://api.india.delta.exchange/v2/history/candles?{query}"

        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get('success'):
                        candles = data.get('result', [])
                        if candles:
                            # Sort chronologically (oldest to newest)
                            candles.sort(key=lambda x: x['time'])
                            return candles[-count:], None
                        else:
                            last_err = "API returned success=true but empty list (probably requested too far in the past)"
                    else:
                        last_err = f"API returned success=false: {data.get('error', {}).get('message', 'Unknown error')}"
                else:
                    last_err = f"HTTP error {response.status}"
        except urllib.error.HTTPError as e:
            if e.code == 429:
                reset_ms = e.headers.get('X-RATE-LIMIT-RESET')
                if reset_ms:
                    reset_sec = float(reset_ms) / 1000.0
                    sleep_dur = min(300.0, reset_sec)
                    print(f"\n{YELLOW}[Rate Limit] Exceeded (HTTP 429). Auto-sleeping for {sleep_dur:.2f}s before retrying...{RESET}")
                    time.sleep(sleep_dur)
                    try:
                        with urllib.request.urlopen(req, timeout=10) as response:
                            if response.status == 200:
                                data = json.loads(response.read().decode('utf-8'))
                                if data.get('success'):
                                    candles = data.get('result', [])
                                    if candles:
                                        candles.sort(key=lambda x: x['time'])
                                        return candles[-count:], None
                    except Exception as retry_err:
                        last_err = f"Failed on rate limit retry: {str(retry_err)}"
                last_err = "API Rate Limit Exceeded (HTTP 429)."
            else:
                # Fallback to global Delta API for other HTTP errors
                fallback_url = f"https://api.delta.exchange/v2/history/candles?{query}"
                req_fallback = urllib.request.Request(fallback_url, headers={'User-Agent': 'Mozilla/5.0'})
                try:
                    with urllib.request.urlopen(req_fallback, timeout=10) as response:
                        if response.status == 200:
                            data = json.loads(response.read().decode('utf-8'))
                            if data.get('success'):
                                candles = data.get('result', [])
                                if candles:
                                    candles.sort(key=lambda x: x['time'])
                                    return candles[-count:], None
                except Exception:
                    pass
                last_err = f"HTTP error {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            # Fallback to global Delta API just in case Delta India is down
            fallback_url = f"https://api.delta.exchange/v2/history/candles?{query}"
            req_fallback = urllib.request.Request(fallback_url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(req_fallback, timeout=10) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode('utf-8'))
                        if data.get('success'):
                            candles = data.get('result', [])
                            if candles:
                                candles.sort(key=lambda x: x['time'])
                                return candles[-count:], None
            except Exception:
                pass
            last_err = f"Failed to connect to API: {e.reason}"
        except Exception as e:
            last_err = f"Unexpected error: {str(e)}"
            
    return [], last_err

def render_ascii_chart(candles, height=12):
    """
    Renders an ASCII candlestick chart for the provided candle list.
    """
    if not candles:
        return "No data to display in chart."

    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]

    max_val = max(highs)
    min_val = min(lows)
    val_range = max_val - min_val

    if val_range == 0:
        val_range = 1.0

    num_candles = len(candles)
    # We use 2 characters per candle (one for candle, one for space)
    grid_width = 2 * num_candles

    grid = [[' ' for _ in range(grid_width)] for _ in range(height)]
    colors = [[RESET for _ in range(grid_width)] for _ in range(height)]

    for i, c in enumerate(candles):
        o, h, l, cl = c['open'], c['high'], c['low'], c['close']
        is_green = cl >= o
        color = GREEN if is_green else RED
        col_idx = 2 * i

        # Calculate row indices (0 is top, height-1 is bottom)
        h_row = int(round((max_val - h) / val_range * (height - 1)))
        l_row = int(round((max_val - l) / val_range * (height - 1)))
        o_row = int(round((max_val - o) / val_range * (height - 1)))
        c_row = int(round((max_val - cl) / val_range * (height - 1)))

        h_row = max(0, min(height - 1, h_row))
        l_row = max(0, min(height - 1, l_row))
        o_row = max(0, min(height - 1, o_row))
        c_row = max(0, min(height - 1, c_row))

        body_start = min(o_row, c_row)
        body_end = max(o_row, c_row)

        # Draw wicks (from high to low)
        for r in range(h_row, l_row + 1):
            grid[r][col_idx] = '│'
            colors[r][col_idx] = color

        # Draw body (overwriting wicks in the body range)
        for r in range(body_start, body_end + 1):
            if o_row == c_row:
                grid[r][col_idx] = '─'
            else:
                grid[r][col_idx] = '█'
            colors[r][col_idx] = color

    lines = []
    # Print the chart lines from top to bottom
    for r in range(height):
        price_r = max_val - r * (val_range / (height - 1))
        scale_str = f"  {price_r:10.2f} │ "
        
        row_chars = []
        for col in range(grid_width):
            row_chars.append(f"{colors[r][col]}{grid[r][col]}{RESET}")
        
        lines.append(scale_str + "".join(row_chars))

    # Add x-axis border
    border_line = " " * 13 + "└" + "─" * grid_width
    lines.append(border_line)
    
    return "\n".join(lines)

def format_timestamp(ts, resolution):
    """Format Unix timestamp based on resolution."""
    dt = datetime.fromtimestamp(ts)
    if resolution.endswith('d') or resolution.endswith('w'):
        return dt.strftime("%Y-%m-%d")
    else:
        return dt.strftime("%m-%d %H:%M")

def calculate_ema(prices, period):
    """
    Calculates the Exponential Moving Average (EMA) for a list of prices.
    Uses Simple Moving Average (SMA) as the initial value.
    """
    if len(prices) < period:
        return [None] * len(prices)
    
    ema_list = [None] * len(prices)
    sma = sum(prices[:period]) / period
    ema_list[period - 1] = sma
    
    k = 2 / (period + 1)
    for i in range(period, len(prices)):
        ema_list[i] = (prices[i] * k) + (ema_list[i-1] * (1 - k))
        
    return ema_list

def calculate_atr(candles, period=14):
    """
    Calculates the Average True Range (ATR).
    """
    if len(candles) < period + 1:
        return [0.0] * len(candles)
        
    tr_list = [0.0]
    for i in range(1, len(candles)):
        high = candles[i]['high']
        low = candles[i]['low']
        prev_close = candles[i-1]['close']
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr_list.append(max(tr1, tr2, tr3))
        
    atr_list = [0.0] * len(candles)
    sma_tr = sum(tr_list[1:period+1]) / period
    atr_list[period] = sma_tr
    
    for i in range(period + 1, len(candles)):
        atr_list[i] = (atr_list[i-1] * (period - 1) + tr_list[i]) / period
        
    return atr_list

def analyze_ema_crossover(candles, fast_period=9, slow_period=21):
    """
    Simulates a Stop-and-Reverse (SAR) EMA Crossover trading strategy.
    Fast EMA vs Slow EMA. Always stays in a position (reversing long/short).
    Tracks entry prices, exits, individual trade returns, and cumulative P&L.
    """
    if len(candles) < slow_period:
        print(f"\n{YELLOW}Warning: Insufficient data for EMA analysis. Need at least {slow_period} candles, got {len(candles)}.{RESET}\n")
        return
        
    closes = [c['close'] for c in candles]
    times = [c['time'] for c in candles]
    
    fast_ema = calculate_ema(closes, fast_period)
    slow_ema = calculate_ema(closes, slow_period)
    
    position = "NONE"  # "LONG", "SHORT", or "NONE"
    entry_price = 0.0
    entry_time = 0
    trades = []
    
    # Simulates trading starting from the first index where slow_ema is available
    start_idx = slow_period - 1
    
    for t in range(start_idx, len(candles)):
        f_val = fast_ema[t]
        s_val = slow_ema[t]
        close_price = closes[t]
        time_val = times[t]
        
        # Bullish Crossover: Fast crosses above Slow
        if f_val > s_val:
            if position != "LONG":
                if position == "SHORT":
                    # Close Short position
                    pnl = ((entry_price - close_price) / entry_price) * 100
                    trades.append({
                        'type': 'SHORT',
                        'entry_time': entry_time,
                        'exit_time': time_val,
                        'entry_price': entry_price,
                        'exit_price': close_price,
                        'pnl': pnl
                    })
                position = "LONG"
                entry_price = close_price
                entry_time = time_val
        # Bearish Crossover: Fast crosses below Slow
        elif f_val < s_val:
            if position != "SHORT":
                if position == "LONG":
                    # Close Long position
                    pnl = ((close_price - entry_price) / entry_price) * 100
                    trades.append({
                        'type': 'LONG',
                        'entry_time': entry_time,
                        'exit_time': time_val,
                        'entry_price': entry_price,
                        'exit_price': close_price,
                        'pnl': pnl
                    })
                position = "SHORT"
                entry_price = close_price
                entry_time = time_val

    print(BOLD + MAGENTA + f"--- EMA Crossover Stop & Reverse (SAR) Simulation ---" + RESET)
    print(f" Strategy Parameters: Fast EMA = {fast_period} | Slow EMA = {slow_period}")
    print(f" Simulated Period:   {format_timestamp(times[start_idx], '1d')} to {format_timestamp(times[-1], '1d')}")
    print()
    
    if trades:
        trade_header = f" {'Trade #':<8} │ {'Type':<6} │ {'Entry Time':<12} │ {'Exit Time':<12} │ {'Entry Price':<12} │ {'Exit Price':<12} │ {'P&L %':<10}"
        print(BOLD + trade_header + RESET)
        print("─" * (len(trade_header) + 1))
        
        cum_pnl = 0.0
        wins = 0
        for idx, t in enumerate(trades, 1):
            pnl_color = GREEN if t['pnl'] >= 0 else RED
            pnl_sign = "+" if t['pnl'] >= 0 else ""
            cum_pnl += t['pnl']
            if t['pnl'] > 0:
                wins += 1
                
            entry_t_str = datetime.fromtimestamp(t['entry_time']).strftime("%m-%d %H:%M")
            exit_t_str = datetime.fromtimestamp(t['exit_time']).strftime("%m-%d %H:%M")
            
            print(f" {idx:<8} │ {t['type']:<6} │ {entry_t_str:<12} │ {exit_t_str:<12} │ {t['entry_price']:<12.4f} │ {t['exit_price']:<12.4f} │ {pnl_color}{pnl_sign}{t['pnl']:.2f}%{RESET}")
            
        win_rate = (wins / len(trades)) * 100 if trades else 0.0
        print("\n" + BOLD + "Simulation Summary Statistics:" + RESET)
        print(f"  Total Completed Trades: {len(trades)}")
        print(f"  Profitable Trades (Wins): {wins} ({win_rate:.2f}% Win Rate)")
        print(f"  Cumulative P&L sum:      {GREEN if cum_pnl >= 0 else RED}{cum_pnl:+.2f}%{RESET}")
    else:
        print("No completed trades inside the simulation window.")
        
    print("\n" + BOLD + "Current Position Status:" + RESET)
    if position != "NONE":
        pos_color = GREEN if position == "LONG" else RED
        curr_price = closes[-1]
        
        if position == "LONG":
            unrealized = ((curr_price - entry_price) / entry_price) * 100
        else: # SHORT
            unrealized = ((entry_price - curr_price) / entry_price) * 100
            
        unrealized_color = GREEN if unrealized >= 0 else RED
        unrealized_sign = "+" if unrealized >= 0 else ""
        
        entry_t_str = datetime.fromtimestamp(entry_time).strftime("%Y-%m-%d %H:%M")
        print(f"  Active Signal:     {pos_color}{position}{RESET}")
        print(f"  Entry Time:        {entry_t_str}")
        print(f"  Entry Price:       {entry_price:.4f} USD")
        print(f"  Unrealized P&L:    {unrealized_color}{unrealized_sign}{unrealized:.2f}%{RESET} (Price: {curr_price:.4f} USD)")
        print(f"  Current Indicators: Fast EMA({fast_period}): {fast_ema[-1]:.4f} | Slow EMA({slow_period}): {slow_ema[-1]:.4f}")
    else:
        print("  Active Signal:     NONE")

def display_dashboard(symbol, resolution, candles, error_msg=None, show_candles=False, show_ema_analysis=False, fast_period=9, slow_period=21):
    """
    Renders and prints the dashboard containing summary info.
    Optionally appends the ASCII candlestick chart, history table, or EMA crossover analysis.
    """
    clear_screen()
    
    # Title Banner
    print(BOLD + CYAN + "┌" + "─"*68 + "┐" + RESET)
    print(BOLD + CYAN + "│" + f" DELTA EXCHANGE REAL-TIME MONITOR ".center(68) + "│" + RESET)
    print(BOLD + CYAN + "└" + "─"*68 + "┘" + RESET)

    if error_msg:
        print(f"\n{RED}{BOLD}ERROR:{RESET} {error_msg}\n")
        return

    if not candles:
        print(f"\n{YELLOW}No candles found for symbol {symbol}.{RESET}\n")
        return

    # Basic stats based on the fetched candles
    latest = candles[-1]
    prev_close = candles[-2]['close'] if len(candles) > 1 else latest['open']
    price_change = latest['close'] - prev_close
    percent_change = (price_change / prev_close) * 100 if prev_close != 0 else 0.0

    color = GREEN if price_change >= 0 else RED
    sign = "+" if price_change >= 0 else ""

    print(f" {BOLD}Asset Symbol:{RESET} {YELLOW}{symbol}{RESET}")
    print(f" {BOLD}Resolution:  {RESET} {SUPPORTED_RESOLUTIONS.get(resolution, resolution)}")
    print(f" {BOLD}Current Price:{RESET} {color}{latest['close']:.4f} USD{RESET} ({color}{sign}{price_change:.4f} | {sign}{percent_change:.2f}%{RESET})")
    print(f" {BOLD}Daily Range:  {RESET} Low: {color}{latest['low']:.4f}{RESET} - High: {color}{latest['high']:.4f}{RESET}")
    print(f" {BOLD}Volume:      {RESET} {latest['volume']:.2f}")
    print(f" {BOLD}Last Updated:{RESET} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Draw ASCII Chart and History Table if explicitly asked
    if show_candles:
        plot_candles = candles
        
        print(BOLD + MAGENTA + f"--- Candlestick Trend Chart (Latest {len(plot_candles)} Candles) ---" + RESET)
        print(render_ascii_chart(plot_candles, height=12))
        print()

        print(BOLD + MAGENTA + "--- Recent Candles History ---" + RESET)
        header = f"{'Date/Time':<15} │ {'Open':<10} │ {'High':<10} │ {'Low':<10} │ {'Close':<10} │ {'Change %':<10} │ {'Volume':<10}"
        print(BOLD + header + RESET)
        print("─" * len(header))

        for i, c in enumerate(plot_candles):
            ts_str = format_timestamp(c['time'], resolution)
            
            if i > 0:
                c_prev = plot_candles[i-1]['close']
                chg = ((c['close'] - c_prev) / c_prev) * 100 if c_prev != 0 else 0
            else:
                chg = ((c['close'] - c['open']) / c['open']) * 100 if c['open'] != 0 else 0

            chg_sign = "+" if chg >= 0 else ""
            chg_color = GREEN if chg >= 0 else RED
            row_color = GREEN if c['close'] >= c['open'] else RED
            
            print(f"{ts_str:<15} │ "
                  f"{c['open']:<10.4f} │ "
                  f"{c['high']:<10.4f} │ "
                  f"{c['low']:<10.4f} │ "
                  f"{row_color}{c['close']:<10.4f}{RESET} │ "
                  f"{chg_color}{chg_sign}{chg:.2f}%{RESET:<10} │ "
                  f"{c['volume']:<10.1f}")
        print()

    # Calculate and render EMA crossover if explicitly asked
    if show_ema_analysis:
        analyze_ema_crossover(candles, fast_period, slow_period)

def display_all_assets_dashboard(resolution='1d'):
    """
    Fetches the latest data for all preconfigured assets and displays
    them together in a unified market overview table.
    """
    clear_screen()
    print(BOLD + CYAN + "┌" + "─"*93 + "┐" + RESET)
    print(BOLD + CYAN + "│" + f" DELTA EXCHANGE - ALL ASSETS MONITOR ({SUPPORTED_RESOLUTIONS.get(resolution, resolution)}) ".center(93) + "│" + RESET)
    print(BOLD + CYAN + "└" + "─"*93 + "┘" + RESET)
    
    header = f" {'Symbol':<10} │ {'Category':<15} │ {'Current Price':<18} │ {'Change %':<10} │ {'24h High':<12} │ {'24h Low':<12} │ {'Volume':<10}"
    print(BOLD + header + RESET)
    print("─" * (len(header) + 1))
    
    # Sort keys to display in numerical choice order (1: SPYX, 2: QQQX, 3: XAUT, etc.)
    for key in sorted(PRECONFIGURED_ASSETS.keys(), key=int):
        asset = PRECONFIGURED_ASSETS[key]
        symbol = asset['symbol']
        category = asset['category']
        
        # We only need the last 2 candles to check current close and compute delta
        candles, err = fetch_candle_data(symbol, resolution, 2)
        if err or not candles:
            print(f" {symbol:<10} │ {category:<15} │ {RED}{'ERROR/NO_DATA':<18}{RESET} │ {RED}{'N/A':<10}{RESET} │ {'-':<12} │ {'-':<12} │ {'-':<10}")
            continue
            
        latest = candles[-1]
        prev_close = candles[-2]['close'] if len(candles) > 1 else latest['open']
        price_change = latest['close'] - prev_close
        percent_change = (price_change / prev_close) * 100 if prev_close != 0 else 0.0

        color = GREEN if price_change >= 0 else RED
        sign = "+" if price_change >= 0 else ""
        
        price_str = f"{latest['close']:.4f} USD"
        change_str = f"{sign}{percent_change:.2f}%"
        
        print(f" {symbol:<10} │ "
              f"{category:<15} │ "
              f"{color}{price_str:<18}{RESET} │ "
              f"{color}{change_str:<10}{RESET} │ "
              f"{latest['high']:<12.4f} │ "
              f"{latest['low']:<12.4f} │ "
              f"{latest['volume']:<10.1f}")
        time.sleep(0.5)
    print()

def get_live_usdt_balance(account_idx=1):
    """Fetches the available USDT margin balance for the specified account."""
    balances, err = make_authenticated_request("GET", "/v2/wallet/balances", account_idx=account_idx)
    if err or not balances:
        return 0.0
    for bal in balances:
        if bal.get('asset_symbol') == 'USDT':
            return float(bal.get('balance', 0.0))
    return 0.0

def run_live_monitor(symbols, resolution, poll_interval=15, trade=False, trade_size=1):
    """
    Periodically polls the specified symbols at poll_interval (seconds).
    Computes EMAs and checks for crossovers.
    Paces requests by sleeping 1s between symbols to control API calls.
    Triggers visual and audio alarms (\a) when a crossover is detected.
    Optionally executes hedged trades across Account 1 (LONG) and Account 2 (SHORT).
    """
    clear_screen()
    print(BOLD + CYAN + "┌" + "─"*68 + "┐" + RESET)
    print(BOLD + CYAN + "│" + f" DELTA EXCHANGE - LIVE CROSSOVER SIGNAL MONITOR ".center(68) + "│" + RESET)
    print(BOLD + CYAN + "│" + f" Polling {len(symbols)} assets every {poll_interval}s. Press Ctrl+C to stop. ".center(68) + "│" + RESET)
    print(BOLD + CYAN + "└" + "─"*68 + "┘" + RESET)
    
    # Configure and print active trading details
    long_acc = 1
    short_acc = 2
    if trade:
        acc1_active = bool(os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY"))
        acc2_active = bool(os.getenv("DELTA_API_KEY_2"))
        acc3_active = bool(os.getenv("DELTA_API_KEY_3"))
        
        if acc3_active:
            long_acc = 3
            short_acc = 3
            
        print(BOLD + YELLOW + "\n=== Automated Trading Mode Active ===" + RESET)
        if acc3_active:
            print(f"  Account 3 (Both LONG/SHORT) is connected.")
            print(f"  All trades (Long and Short) will route to Account 3.")
        elif acc1_active and acc2_active:
            print(f"  Account 1 (Main/LONG) and Account 2 (Sub/SHORT) are both connected.")
            print(f"  Long trades will route to Account 1; Short trades will route to Account 2.")
        elif acc1_active:
            print(f"  {YELLOW}Warning: Only Account 1 is connected. Shorts will fail to execute because Account 2 is missing.{RESET}")
        else:
            print(f"  {RED}Error: No trading accounts connected. Falling back to Alert-Only mode.{RESET}")
            trade = False
        print(f"  Default Order Size: {trade_size} contracts")
        time.sleep(2.5)
        
    opt_settings = load_optimized_settings()
    states = {}
    trade_details = {}
    last_evaluated_candle_time = {}
    alerts = []
    
    # First, initialize states
    print(f"\n{YELLOW}Initializing crossover tracking states...{RESET}")
    for symbol in symbols:
        fast_period = 9
        slow_period = 21
        opt_key = f"{symbol}_{resolution}"
        if opt_key in opt_settings:
            fast_period = opt_settings[opt_key].get("fast_period", 9)
            slow_period = opt_settings[opt_key].get("slow_period", 21)
            print(f"  {symbol}: Using GA optimized parameters Fast EMA({fast_period}) / Slow EMA({slow_period}).")
            
        candles, err = fetch_candle_data(symbol, resolution, slow_period + 45)
        if err or not candles or len(candles) < 2:
            print(f"  {symbol}: {RED}Error initializing ({err or 'No data'}){RESET}")
            states[symbol] = "ERROR"
            continue
            
        closes = [c['close'] for c in candles]
        fast_ema = calculate_ema(closes, fast_period)
        slow_ema = calculate_ema(closes, slow_period)
        
        if len(fast_ema) < slow_period + 2 or fast_ema[-2] is None or slow_ema[-2] is None:
            states[symbol] = "ERROR"
            continue
            
        curr_state = "LONG" if fast_ema[-2] > slow_ema[-2] else "SHORT"
        states[symbol] = curr_state
        trade_details[symbol] = {'entry_price': 0, 'avg_price': 0, 'pyramid_count': 0, 'highest': 0, 'lowest': 0, 'stop_loss': 0}
        last_evaluated_candle_time[symbol] = candles[-2]['time']
        print(f"  {symbol}: Tracked. Current state is {GREEN if curr_state=='LONG' else RED}{curr_state}{RESET} (Fast: {fast_ema[-2]:.4f} | Slow: {slow_ema[-2]:.4f})")
        time.sleep(1) # Pacing API requests
        
    print(f"\n{GREEN}Initialization complete. Live monitoring active...{RESET}")
    time.sleep(1.5)
    
    try:
        while True:
            start_time = time.time()
            clear_screen()
            print(BOLD + CYAN + "┌" + "─"*80 + "┐" + RESET)
            print(BOLD + CYAN + "│" + f" DELTA EXCHANGE LIVE CROSSOVER SCANNER ({SUPPORTED_RESOLUTIONS.get(resolution, resolution)}) ".center(80) + "│" + RESET)
            print(BOLD + CYAN + "│" + f" Last Poll: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Polling Interval: {poll_interval}s ".center(80) + "│" + RESET)
            print(BOLD + CYAN + "└" + "─"*80 + "┘" + RESET)
            
            # Print status table
            table_header = f" {'Symbol':<10} │ {'Price':<12} │ {'Fast':<10} │ {'Slow':<10} │ {'Macro':<10} │ {'ATR':<10} │ {'State':<12}"
            print(BOLD + table_header + RESET)
            print("─" * (len(table_header) + 1))
            
            for symbol in symbols:
                fast_period = 9
                slow_period = 21
                opt_key = f"{symbol}_{resolution}"
                if opt_key in opt_settings:
                    fast_period = opt_settings[opt_key].get("fast_period", 9)
                    slow_period = opt_settings[opt_key].get("slow_period", 21)
                    
                req_candles = (slow_period * 4) + 45
                
                if symbol not in states or states[symbol] == "ERROR":
                    # Try to re-initialize
                    candles, err = fetch_candle_data(symbol, resolution, req_candles)
                    if not err and candles and len(candles) >= 2:
                        closes = [c['close'] for c in candles]
                        fast_ema = calculate_ema(closes, fast_period)
                        slow_ema = calculate_ema(closes, slow_period)
                        macro_ema = calculate_ema(closes, slow_period * 4)
                        if len(fast_ema) >= slow_period + 2 and fast_ema[-2] is not None and slow_ema[-2] is not None and macro_ema[-2] is not None:
                            # Advanced MTF Entry
                            if fast_ema[-2] > slow_ema[-2] and closes[-2] > macro_ema[-2]:
                                states[symbol] = "LONG"
                            elif fast_ema[-2] < slow_ema[-2] and closes[-2] < macro_ema[-2]:
                                states[symbol] = "SHORT"
                            else:
                                states[symbol] = "FLAT"
                            last_evaluated_candle_time[symbol] = candles[-2]['time']
                    
                if symbol not in states or states[symbol] == "ERROR":
                    print(f" {symbol:<10} │ {RED}{'ERR_FETCH':<12}{RESET} │ {'-':<10} │ {'-':<10} │ {'-':<10} │ {'-':<10} │ {RED}{'ERROR':<12}{RESET}")
                    states[symbol] = "ERROR"
                    continue
                    
                # Fetch latest candle data
                candles, err = fetch_candle_data(symbol, resolution, req_candles)
                if err or not candles or len(candles) < 2:
                    print(f" {symbol:<10} │ {YELLOW}{'STALE':<12}{RESET} │ {'-':<10} │ {'-':<10} │ {'-':<10} │ {'-':<10} │ {states[symbol]:<12}")
                    continue
                    
                closes = [c['close'] for c in candles]
                fast_ema = calculate_ema(closes, fast_period)
                slow_ema = calculate_ema(closes, slow_period)
                macro_ema = calculate_ema(closes, slow_period * 4)
                atr_vals = calculate_atr(candles, 14)
                
                f_val = fast_ema[-1]
                s_val = slow_ema[-1]
                m_val = macro_ema[-1]
                curr_atr = atr_vals[-1]
                latest_close = closes[-1]
                
                if m_val is None:
                    macro_str = "-"
                    macro_color = RESET
                else:
                    is_bull = latest_close > m_val
                    macro_str = "BULL" if is_bull else "BEAR"
                    macro_color = GREEN if is_bull else RED
                
                # Check for crossover only when a new candle closes
                closed_candle_time = candles[-2]['time']
                if symbol not in last_evaluated_candle_time:
                    last_evaluated_candle_time[symbol] = closed_candle_time
                    
                if closed_candle_time > last_evaluated_candle_time[symbol]:
                    f_closed = fast_ema[-2]
                    s_closed = slow_ema[-2]
                    m_closed = macro_ema[-2]
                    cl_closed = closes[-2]
                    
                    if f_closed is not None and s_closed is not None and m_closed is not None:
                        new_state = states[symbol]
                        
                        if f_closed > s_closed and cl_closed > m_closed:
                            new_state = "LONG"
                        elif f_closed < s_closed and cl_closed < m_closed:
                            new_state = "SHORT"
                            
                        if new_state != states[symbol]:
                            print("\a", end="")
                            alert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            alerts.append(f"[{alert_time}] ★ {symbol} crossed over to {new_state} at {closes[-2]:.4f} USD")
                            states[symbol] = new_state
                            td = trade_details[symbol]
                            
                            if trade:
                                if new_state == "LONG":
                                    print(f"\n{GREEN}[Trade Action] LONG crossover triggered for {symbol}.{RESET}")
                                    td['entry_price'] = cl_closed
                                    td['avg_price'] = cl_closed
                                    td['highest'] = cl_closed
                                    td['stop_loss'] = cl_closed - (curr_atr * 2)
                                    td['pyramid_count'] = 0
                                    
                                    close_res, close_err = close_position_if_any(symbol, account_idx=short_acc)
                                    if close_err:
                                        print(f"  {RED}[ERROR] Close short position failed: {close_err}{RESET}")
                                    
                                    # Fractional Kelly Sizing
                                    balance = get_live_usdt_balance(account_idx=long_acc)
                                    sl_distance = curr_atr * 2
                                    dynamic_size = trade_size
                                    actual_size = max(1, int(dynamic_size))
                                    if balance > 0 and sl_distance > 0:
                                        dynamic_size = (balance * 0.02) / sl_distance
                                        print(f"  {CYAN}Calculated Kelly Lot Size: {dynamic_size:.3f} (Bal: ${balance:.2f}, Risk: 2%, SL: ${sl_distance:.2f}){RESET}")
                                        
                                        actual_size = max(1, int(dynamic_size))
                                        pct_risk = (actual_size * sl_distance) / balance
                                        if pct_risk > 0.05:
                                            print(f"  {RED}[WARNING: Burner Phase / Over-Leveraged] Due to low balance, this trade will risk {pct_risk*100.0:.1f}% of equity instead of 2.0% Kelly limits!{RESET}")
                                    
                                    order_res, order_err = place_market_order(symbol, "buy", size=actual_size, account_idx=long_acc)
                                    if order_err:
                                        print(f"  {RED}[ERROR] Order placement failed: {order_err}{RESET}")
                                    else:
                                        print(f"  {GREEN}[SUCCESS] LONG order placed successfully.{RESET}")
                                elif new_state == "SHORT":
                                    print(f"\n{RED}[Trade Action] SHORT crossover triggered for {symbol}.{RESET}")
                                    td['entry_price'] = cl_closed
                                    td['avg_price'] = cl_closed
                                    td['lowest'] = cl_closed
                                    td['stop_loss'] = cl_closed + (curr_atr * 2)
                                    td['pyramid_count'] = 0
                                    
                                    close_res, close_err = close_position_if_any(symbol, account_idx=long_acc)
                                    if close_err:
                                        print(f"  {RED}[ERROR] Close long position failed: {close_err}{RESET}")
                                    
                                    # Fractional Kelly Sizing
                                    balance = get_live_usdt_balance(account_idx=short_acc)
                                    sl_distance = curr_atr * 2
                                    dynamic_size = trade_size
                                    actual_size = max(1, int(dynamic_size))
                                    if balance > 0 and sl_distance > 0:
                                        dynamic_size = (balance * 0.02) / sl_distance
                                        print(f"  {CYAN}Calculated Kelly Lot Size: {dynamic_size:.3f} (Bal: ${balance:.2f}, Risk: 2%, SL: ${sl_distance:.2f}){RESET}")
                                        
                                        actual_size = max(1, int(dynamic_size))
                                        pct_risk = (actual_size * sl_distance) / balance
                                        if pct_risk > 0.05:
                                            print(f"  {RED}[WARNING: Burner Phase / Over-Leveraged] Due to low balance, this trade will risk {pct_risk*100.0:.1f}% of equity instead of 2.0% Kelly limits!{RESET}")
                                        
                                    order_res, order_err = place_market_order(symbol, "sell", size=actual_size, account_idx=short_acc)
                                    if order_err:
                                        print(f"  {RED}[ERROR] Order placement failed: {order_err}{RESET}")
                                    else:
                                        print(f"  {GREEN}[SUCCESS] SHORT order placed successfully.{RESET}")
                        
                        last_evaluated_candle_time[symbol] = closed_candle_time
                
                # --- LIVE STATE ENGINE: Pyramiding & Trailing Stops ---
                td = trade_details[symbol]
                if states[symbol] == "LONG":
                    if latest_close > td['highest']:
                        td['highest'] = latest_close
                        new_sl = latest_close - (curr_atr * 2)
                        if new_sl > td['stop_loss']:
                            td['stop_loss'] = new_sl
                            
                    if latest_close <= td['stop_loss'] and td['entry_price'] > 0:
                        print(f"\n{YELLOW}[Trailing Stop] {symbol} hit Long trailing stop at {latest_close:.4f}{RESET}")
                        if trade:
                            close_res, close_err = close_position_if_any(symbol, account_idx=long_acc)
                            if close_err:
                                print(f"  {RED}[ERROR] Close trailing stop failed: {close_err}{RESET}")
                        states[symbol] = "FLAT"
                        td['entry_price'] = 0
                        
                    elif td['entry_price'] > 0 and latest_close >= td['avg_price'] + (curr_atr * 1.5) and td['pyramid_count'] < 3:
                        print(f"\n{GREEN}[Pyramid] {symbol} Long moved +1.5 ATR. Scaling in (Layer {td['pyramid_count']+1})!{RESET}")
                        if trade:
                            balance = get_live_usdt_balance(account_idx=long_acc)
                            sl_distance = curr_atr * 2
                            dynamic_size = trade_size
                            if balance > 0 and sl_distance > 0:
                                dynamic_size = (balance * 0.01) / sl_distance # Half-Kelly for Pyramids
                            actual_size = max(1, int(dynamic_size))
                            order_res, order_err = place_market_order(symbol, "buy", size=actual_size, account_idx=long_acc)
                            if order_err:
                                print(f"  {RED}[ERROR] Pyramid order failed: {order_err}{RESET}")
                        td['avg_price'] = (td['avg_price'] + latest_close) / 2
                        td['pyramid_count'] += 1

                elif states[symbol] == "SHORT":
                    if td['lowest'] == 0 or latest_close < td['lowest']:
                        td['lowest'] = latest_close
                        new_sl = latest_close + (curr_atr * 2)
                        if td['stop_loss'] == 0 or new_sl < td['stop_loss']:
                            td['stop_loss'] = new_sl
                            
                    if latest_close >= td['stop_loss'] and td['entry_price'] > 0:
                        print(f"\n{YELLOW}[Trailing Stop] {symbol} hit Short trailing stop at {latest_close:.4f}{RESET}")
                        if trade:
                            close_res, close_err = close_position_if_any(symbol, account_idx=short_acc)
                            if close_err:
                                print(f"  {RED}[ERROR] Close trailing stop failed: {close_err}{RESET}")
                        states[symbol] = "FLAT"
                        td['entry_price'] = 0
                        
                    elif td['entry_price'] > 0 and latest_close <= td['avg_price'] - (curr_atr * 1.5) and td['pyramid_count'] < 3:
                        print(f"\n{RED}[Pyramid] {symbol} Short moved +1.5 ATR. Scaling in (Layer {td['pyramid_count']+1})!{RESET}")
                        if trade:
                            balance = get_live_usdt_balance(account_idx=short_acc)
                            sl_distance = curr_atr * 2
                            dynamic_size = trade_size
                            if balance > 0 and sl_distance > 0:
                                dynamic_size = (balance * 0.01) / sl_distance # Half-Kelly for Pyramids
                            actual_size = max(1, int(dynamic_size))
                            order_res, order_err = place_market_order(symbol, "sell", size=actual_size, account_idx=short_acc)
                            if order_err:
                                print(f"  {RED}[ERROR] Pyramid order failed: {order_err}{RESET}")
                        td['avg_price'] = (td['avg_price'] + latest_close) / 2
                        td['pyramid_count'] += 1
                # ------------------------------------------------------
                
                if states[symbol] == "LONG":
                    pos_color = GREEN
                elif states[symbol] == "SHORT":
                    pos_color = RED
                else:
                    pos_color = YELLOW
                    
                print(f" {symbol:<10} │ {latest_close:<12.4f} │ {f_val:<10.2f} │ {s_val:<10.2f} │ {macro_color}{macro_str:<10}{RESET} │ {curr_atr:<10.4f} │ {pos_color}{states[symbol]:<12}{RESET}")
                
                # Pace API requests by 1 second to prevent rate limiting
                time.sleep(1)
                
            # Print alerts log
            print("\n" + BOLD + MAGENTA + "--- Crossover Alerts Log (Latest 5) ---" + RESET)
            if alerts:
                for a in alerts[-5:]:
                    print(f" {GREEN if 'LONG' in a else RED}{a}{RESET}")
            else:
                print(f" {DARK_GRAY}No crossover alerts detected yet. Scanning...{RESET}")
                
            # Account for loop execution time to enforce an accurate polling sleep
            elapsed = time.time() - start_time
            sleep_time = max(1, poll_interval - elapsed)
            
            print(f"\n{DARK_GRAY}Sleeping for {sleep_time:.1f}s. Press Ctrl+C to exit...{RESET}")
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Monitoring stopped by user.{RESET}")

def interactive_mode():
    """Run interactive CLI menu."""
    load_env()
    cached_balance = None
    cached_balance_time = 0
    
    while True:
        clear_screen()
        menu_acc_idx = None
        if os.getenv("DELTA_API_KEY_3"):
            menu_acc_idx = 3
        elif os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY"):
            menu_acc_idx = 1
        elif os.getenv("DELTA_API_KEY_2"):
            menu_acc_idx = 2
            
        api_key = None
        api_secret = None
        acc_name = ""
        if menu_acc_idx == 3:
            api_key = os.getenv("DELTA_API_KEY_3")
            api_secret = os.getenv("DELTA_API_SECRET_3")
            acc_name = "Account 3"
        elif menu_acc_idx == 2:
            api_key = os.getenv("DELTA_API_KEY_2")
            api_secret = os.getenv("DELTA_API_SECRET_2")
            acc_name = "Account 2"
        elif menu_acc_idx == 1:
            api_key = os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY")
            api_secret = os.getenv("DELTA_API_SECRET_1") or os.getenv("DELTA_API_SECRET")
            acc_name = "Account 1"
            
        status_label = f"Connected ({acc_name})" if menu_acc_idx else "Disconnected"
        color_status = f"{GREEN}Connected ({acc_name}){RESET}" if menu_acc_idx else f"{RED}Disconnected{RESET}"
        
        # Load user balance once or update every 15s to keep CMD responsive without rate limit exhaustion
        if api_key and api_secret:
            now = time.time()
            if cached_balance is None or now - cached_balance_time > 15:
                balances, err = make_authenticated_request("GET", "/v2/wallet/balances", account_idx=menu_acc_idx)
                if not err and balances:
                    found = False
                    for bal in balances:
                        if bal.get('asset_symbol') in ['USDT', 'DET', 'INR']:
                            cached_balance = f"{float(bal.get('balance', 0)):,.2f} {bal.get('asset_symbol')}"
                            found = True
                            break
                    if not found and len(balances) > 0:
                        non_zero = [b for b in balances if float(b.get('balance', 0)) > 0]
                        if non_zero:
                            cached_balance = f"{float(non_zero[0].get('balance', 0)):,.2f} {non_zero[0].get('asset_symbol')}"
                        else:
                            cached_balance = f"{float(balances[0].get('balance', 0)):,.2f} {balances[0].get('asset_symbol')}"
                    cached_balance_time = now
                elif err:
                    cached_balance = f"Error: {err}"
        else:
            cached_balance = None
            
        print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
        print(BOLD + CYAN + "│" + f" DELTA EXCHANGE MONITOR MENU ".center(50) + "│" + RESET)
        print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
        
        # Draw status line with dynamic padding
        status_line = f"  Account Status: {color_status}"
        visible_status_len = len(f"  Account Status: {status_label}")
        ansi_extra_status = len(status_line) - visible_status_len
        print(BOLD + CYAN + "│" + f"{status_line:<{48 + ansi_extra_status}}" + "│" + RESET)
        
        # Draw balance line
        if api_key:
            bal_str = cached_balance if cached_balance else "Loading..."
            bal_line = f"  Balance: {YELLOW}{bal_str}{RESET}"
            visible_bal_len = len(f"  Balance: {bal_str}")
            ansi_extra_bal = len(bal_line) - visible_bal_len
            print(BOLD + CYAN + "│" + f"{bal_line:<{48 + ansi_extra_bal}}" + "│" + RESET)
        else:
            print(BOLD + CYAN + "│" + f"  (Use option 10 to connect your account)".ljust(48) + "│" + RESET)
            
        print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
        
        # Print preconfigured choices (1-6)
        for key, val in PRECONFIGURED_ASSETS.items():
            line = f"  {key}. {val['name']} [{val['category']}]"
            print(BOLD + CYAN + "│" + f"{line:<48}" + "│" + RESET)
            
        all_line = "  7. Run All Assets (Combined Table)"
        custom_line = "  8. Custom Symbol (e.g. BTCUSD, AAPLXUSD)"
        monitor_line = "  9. Live Crossover Monitor (Alert Mode)"
        account_line = " 10. API Account Settings (Connected Portfolio)" if api_key else " 10. Connect API Credentials (Add Keys)"
        opt_line = " 11. Run Genetic Strategy Optimizer (EMA GA)"
        daemon_line = " 12. Background Daemon Controls (Start/Stop)"
        auto_line = " 13. Fully Autonomous Auto-Pilot Setup"
        exit_line = "  Q. Exit"
        print(BOLD + CYAN + "│" + f"{all_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "│" + f"{custom_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "│" + f"{monitor_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "│" + f"{account_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "│" + f"{opt_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "│" + f"{daemon_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "│" + f"{auto_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "│" + f"{exit_line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
        
        choice = input(BOLD + "\nSelect an option (1-13, Q to quit): " + RESET).strip()
        
        if choice.lower() == 'q':
            print("Exiting Monitor. Goodbye!")
            sys.exit(0)
            
        symbol = ""
        if choice in PRECONFIGURED_ASSETS:
            symbol = PRECONFIGURED_ASSETS[choice]['symbol']
        elif choice == '7':
            symbol = "ALL"
        elif choice == '8':
            print(f"\n{YELLOW}Popular symbols on Delta Exchange:{RESET}")
            print(f"  {CYAN}Cryptocurrencies:{RESET} BTCUSD, ETHUSD, SOLUSD, XRPUSD, BNBUSD, AVAXUSD, SUIUSD, DOGEUSD, PEPEUSD")
            print(f"  {CYAN}Stock Indices:{RESET}    SPYXUSD, QQQXUSD")
            print(f"  {CYAN}Commodities:{RESET}      XAUTUSD, SLVONUSD\n")
            symbol = input(BOLD + "Enter Delta Exchange symbol: " + RESET).strip().upper()
            if not symbol:
                print("Invalid Symbol. Press Enter to return.")
                input()
                continue
        elif choice == '9':
            clear_screen()
            print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
            print(BOLD + CYAN + "│" + f" SELECT ASSETS TO MONITOR ".center(50) + "│" + RESET)
            print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
            print(BOLD + CYAN + "│" + f"  1. Monitor All Preconfigured Assets".ljust(48) + "│" + RESET)
            print(BOLD + CYAN + "│" + f"  2. Monitor Specific Custom Symbol".ljust(48) + "│" + RESET)
            print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
            
            mon_choice = input(BOLD + "\nSelect choice (1-2): " + RESET).strip()
            symbols = []
            if mon_choice == '1':
                symbols = [PRECONFIGURED_ASSETS[k]['symbol'] for k in sorted(PRECONFIGURED_ASSETS.keys(), key=int)]
            elif mon_choice == '2':
                print(f"\n{YELLOW}Popular symbols on Delta Exchange:{RESET}")
                print(f"  {CYAN}Cryptocurrencies:{RESET} BTCUSD, ETHUSD, SOLUSD, XRPUSD, BNBUSD, AVAXUSD, SUIUSD, DOGEUSD, PEPEUSD")
                print(f"  {CYAN}Stock Indices:{RESET}    SPYXUSD, QQQXUSD")
                print(f"  {CYAN}Commodities:{RESET}      XAUTUSD, SLVONUSD\n")
                sym = input(BOLD + "Enter symbol to monitor: " + RESET).strip().upper()
                if sym:
                    symbols = [sym]
                else:
                    print("Invalid Symbol. Press Enter to return.")
                    input()
                    continue
            else:
                continue

            clear_screen()
            print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
            print(BOLD + CYAN + "│" + f" CHOOSE MONITOR TIMEFRAME ".center(50) + "│" + RESET)
            print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
            sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
            for idx, res in enumerate(sorted_resolutions, 1):
                line = f"  {idx}. {res} ({SUPPORTED_RESOLUTIONS[res]})"
                print(BOLD + CYAN + "│" + f"{line:<48}" + "│" + RESET)
            print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
            
            res_choice = input(BOLD + "\nSelect resolution (1-8, Default 1m): " + RESET).strip()
            resolution = '1m'
            if res_choice.isdigit():
                idx = int(res_choice) - 1
                if 0 <= idx < len(sorted_resolutions):
                    resolution = sorted_resolutions[idx]

            int_input = input(BOLD + "Enter polling interval in seconds (5-300, Default 15): " + RESET).strip()
            poll_interval = 15
            if int_input.isdigit():
                poll_interval = max(5, min(300, int(int_input)))

            # Ask if they want to enable automated trade routing
            trade_mode = False
            trade_size = 1
            api_active = bool(os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY") or os.getenv("DELTA_API_KEY_3"))
            if api_active:
                trade_choice = input(BOLD + "Enable Automated Crossover Trading? (y/N): " + RESET).strip().lower()
                if trade_choice == 'y':
                    trade_mode = True
                    size_input = input(BOLD + "Enter trade contract size (Default 1): " + RESET).strip()
                    if size_input.isdigit():
                        trade_size = max(1, int(size_input))

            run_live_monitor(symbols, resolution, poll_interval, trade=trade_mode, trade_size=trade_size)
            input(BOLD + "\nPress Enter to return to menu... " + RESET)
            continue
        elif choice == '10':
            while True:
                clear_screen()
                api_key_1 = os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY")
                api_key_2 = os.getenv("DELTA_API_KEY_2")
                api_key_3 = os.getenv("DELTA_API_KEY_3")
                
                status_1 = f"{GREEN}Connected{RESET}" if api_key_1 else f"{RED}Disconnected{RESET}"
                status_2 = f"{GREEN}Connected{RESET}" if api_key_2 else f"{RED}Disconnected{RESET}"
                status_3 = f"{GREEN}Connected{RESET}" if api_key_3 else f"{RED}Disconnected{RESET}"
                
                print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
                print(BOLD + CYAN + "│" + f" DELTA MULTI-ACCOUNT SETTINGS ".center(50) + "│" + RESET)
                print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
                print(f"  Account 1 (Main/LONG):       {status_1}")
                print(f"  Account 2 (Sub/SHORT):       {status_2}")
                print(f"  Account 3 (Both LONG/SHORT): {status_3}")
                print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
                print(BOLD + CYAN + "│" + f"  1. Connect / Update Account 1 (Main/LONG)".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  2. Disconnect Account 1".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  3. Connect / Update Account 2 (Sub/SHORT)".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  4. Disconnect Account 2".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  5. Connect / Update Account 3 (Both LONG/SHORT)".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  6. Disconnect Account 3".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  7. View Portfolio Balances & Positions".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  B. Back to Main Menu".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
                
                sub_opt = input(BOLD + "\nSelect choice (1-7, B): " + RESET).strip().upper()
                if sub_opt == '1':
                    key_input = input("Enter API Key for Account 1: ").strip()
                    secret_input = input("Enter API Secret for Account 1: ").strip()
                    if key_input and secret_input:
                        save_env_keys(1, key_input, secret_input)
                        load_env()
                        cached_balance = None
                        cached_balance_time = 0
                        print(f"\n{GREEN}Account 1 credentials saved successfully!{RESET}")
                    else:
                        print(f"\n{RED}Error: Fields cannot be empty.{RESET}")
                    time.sleep(2)
                elif sub_opt == '2':
                    remove_env_keys(1)
                    load_env()
                    cached_balance = None
                    cached_balance_time = 0
                    print(f"\n{YELLOW}Account 1 disconnected.{RESET}")
                    time.sleep(2)
                elif sub_opt == '3':
                    key_input = input("Enter API Key for Account 2: ").strip()
                    secret_input = input("Enter API Secret for Account 2: ").strip()
                    if key_input and secret_input:
                        save_env_keys(2, key_input, secret_input)
                        load_env()
                        print(f"\n{GREEN}Account 2 credentials saved successfully!{RESET}")
                    else:
                        print(f"\n{RED}Error: Fields cannot be empty.{RESET}")
                    time.sleep(2)
                elif sub_opt == '4':
                    remove_env_keys(2)
                    load_env()
                    print(f"\n{YELLOW}Account 2 disconnected.{RESET}")
                    time.sleep(2)
                elif sub_opt == '5':
                    key_input = input("Enter API Key for Account 3: ").strip()
                    secret_input = input("Enter API Secret for Account 3: ").strip()
                    if key_input and secret_input:
                        save_env_keys(3, key_input, secret_input)
                        load_env()
                        print(f"\n{GREEN}Account 3 credentials saved successfully!{RESET}")
                    else:
                        print(f"\n{RED}Error: Fields cannot be empty.{RESET}")
                    time.sleep(2)
                elif sub_opt == '6':
                    remove_env_keys(3)
                    load_env()
                    print(f"\n{YELLOW}Account 3 disconnected.{RESET}")
                    time.sleep(2)
                elif sub_opt == '7':
                    fetch_and_show_account()
                    input(BOLD + "\nPress Enter to return... " + RESET)
                elif sub_opt == 'B':
                    break
                else:
                    print(f"{RED}Invalid Option.{RESET}")
                    time.sleep(1)
            continue
        elif choice == '11':
            clear_screen()
            print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
            print(BOLD + CYAN + "│" + f" GENETIC ALGORITHM OPTIMIZER ".center(50) + "│" + RESET)
            print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
            print(f"\n{YELLOW}Popular symbols on Delta Exchange:{RESET}")
            print(f"  {CYAN}Cryptocurrencies:{RESET} BTCUSD, ETHUSD, SOLUSD, XRPUSD, BNBUSD, AVAXUSD, SUIUSD, DOGEUSD, PEPEUSD")
            print(f"  {CYAN}Stock Indices:{RESET}    SPYXUSD, QQQXUSD")
            print(f"  {CYAN}Commodities:{RESET}      XAUTUSD, SLVONUSD\n")
            sym = input(BOLD + "Enter symbol to optimize: " + RESET).strip().upper()
            if not sym:
                continue
                
            print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
            print(BOLD + CYAN + "│" + f" SELECT OPTIMIZATION TIMEFRAME ".center(50) + "│" + RESET)
            print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
            sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
            for idx, res in enumerate(sorted_resolutions, 1):
                line = f"  {idx}. {res} ({SUPPORTED_RESOLUTIONS[res]})"
                print(BOLD + CYAN + "│" + f"{line:<48}" + "│" + RESET)
            print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
            
            print(f"\n{YELLOW}[Help: Select the timeframe/candle size. '1h' or '4h' is recommended.]{RESET}")
            res_choice = input(BOLD + "Select resolution (1-8, Default 1d): " + RESET).strip()
            resolution = parse_resolution_input(res_choice, '1d')
                    
            print(f"\n{YELLOW}[Help: META tuning optimizes the optimizer's speed and depth. It takes longer but is more thorough. Recommended: 'n'.]{RESET}")
            meta_choice = input(BOLD + "Run META hyperparameter optimization first? (y/N): " + RESET).strip().lower()
            if meta_choice == 'y':
                meta_gens = get_validated_int_input(
                    "Enter Meta-GA generations (Default 5): ",
                    "Number of optimization tuning cycles. Recommended 5, Max 20 (higher values can take hours).",
                    5, 1, 20
                )
                meta_pop = get_validated_int_input(
                    "Enter Meta-GA population size (Default 10): ",
                    "Number of candidate configurations per cycle. Recommended 10, Max 30.",
                    10, 5, 30
                )
                run_meta_genetic_optimization(sym, resolution, meta_gens, meta_pop)
            else:
                generations = get_validated_int_input(
                    "Enter number of GA generations (Default 15): ",
                    "Evolution cycles for finding best EMAs. Recommended 15, Max 50.",
                    15, 1, 50
                )
                run_genetic_optimization(sym, resolution, generations)
                
            input(BOLD + "\nPress Enter to return to menu... " + RESET)
            continue
            
        elif choice == '12':
            while True:
                clear_screen()
                print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
                print(BOLD + CYAN + "│" + f" BACKGROUND DAEMON CONTROLS ".center(50) + "│" + RESET)
                print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
                print(BOLD + CYAN + "│" + f"  1. Start Background Daemon Monitor".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  2. Check Background Daemon Status & Logs".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  3. Stop Background Daemon".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "│" + f"  B. Back to Main Menu".ljust(48) + "│" + RESET)
                print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
                
                sub_opt = input(BOLD + "\nSelect choice (1-3, B): " + RESET).strip().upper()
                if sub_opt == '1':
                    clear_screen()
                    print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
                    print(BOLD + CYAN + "│" + f" START BACKGROUND MONITOR ".center(50) + "│" + RESET)
                    print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
                    print(BOLD + CYAN + "│" + f"  1. Monitor All Preconfigured Assets".ljust(48) + "│" + RESET)
                    print(BOLD + CYAN + "│" + f"  2. Monitor Specific Custom Symbol".ljust(48) + "│" + RESET)
                    print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
                    
                    mon_choice = input(BOLD + "\nSelect choice (1-2): " + RESET).strip()
                    symbols = []
                    if mon_choice == '1':
                        symbols = [PRECONFIGURED_ASSETS[k]['symbol'] for k in sorted(PRECONFIGURED_ASSETS.keys(), key=int)]
                    elif mon_choice == '2':
                        print(f"\n{YELLOW}Popular symbols on Delta Exchange:{RESET}")
                        print(f"  {CYAN}Cryptocurrencies:{RESET} BTCUSD, ETHUSD, SOLUSD, XRPUSD, BNBUSD, AVAXUSD, SUIUSD, DOGEUSD, PEPEUSD")
                        print(f"  {CYAN}Stock Indices:{RESET}    SPYXUSD, QQQXUSD")
                        print(f"  {CYAN}Commodities:{RESET}      XAUTUSD, SLVONUSD\n")
                        sym = input(BOLD + "Enter symbol: " + RESET).strip().upper()
                        if sym:
                            symbols = [sym]
                    if not symbols:
                        print("Invalid selection.")
                        time.sleep(1.5)
                        continue
                        
                    print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
                    print(BOLD + CYAN + "│" + f" SELECT RESOLUTION ".center(50) + "│" + RESET)
                    print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
                    sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
                    for idx, res in enumerate(sorted_resolutions, 1):
                        line = f"  {idx}. {res} ({SUPPORTED_RESOLUTIONS[res]})"
                        print(BOLD + CYAN + "│" + f"{line:<48}" + "│" + RESET)
                    print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
                    
                    print(f"\n{YELLOW}[Help: Select the timeframe/candle size. '1h' or '4h' is recommended.]{RESET}")
                    res_choice = input(BOLD + "Select resolution (1-8, Default 1m): " + RESET).strip()
                    resolution = parse_resolution_input(res_choice, '1m')
                            
                    poll_interval = get_validated_int_input(
                        "Enter polling interval in seconds (5-300, Default 15): ",
                        "How often the bot checks for new candles and calculates crossovers. Min 5s, Max 300s.",
                        15, 5, 300
                    )
                        
                    daemon_args = []
                    if mon_choice == '1':
                        daemon_args += ["--symbol", "ALL"]
                    else:
                        daemon_args += ["--symbol", symbols[0]]
                    daemon_args += ["--resolution", resolution, "--monitor", "--poll-interval", str(poll_interval)]
                    
                    api_active = bool(os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY") or os.getenv("DELTA_API_KEY_3"))
                    if api_active:
                        print(f"\n{YELLOW}[Help: Type 'y' to allow the bot to place real trades using your account keys.]{RESET}")
                        trade_choice = input(BOLD + "Enable Crossover Trading? (y/N): " + RESET).strip().lower()
                        if trade_choice == 'y':
                            daemon_args += ["--trade"]
                            trade_size_val = get_validated_int_input(
                                "Enter trade contract size (Default 1): ",
                                "The fallback order size if dynamic Kelly balance is unavailable. Min 1, Max 1000.",
                                1, 1, 1000
                            )
                            daemon_args += ["--trade-size", str(trade_size_val)]
                                
                    start_daemon(daemon_args)
                    time.sleep(2)
                elif sub_opt == '2':
                    clear_screen()
                    check_daemon_status()
                    input(BOLD + "\nPress Enter to return... " + RESET)
                elif sub_opt == '3':
                    clear_screen()
                    stop_daemon()
                    time.sleep(2)
                elif sub_opt == 'B':
                    break
            continue
            
        elif choice == '13':
            run_autopilot_setup('1h', 10)
            input(BOLD + "\nPress Enter to return to menu... " + RESET)
            continue
            
        else:
            print("Invalid Choice. Press Enter to retry.")
            input()
            continue

        # Choose resolution
        clear_screen()
        print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
        print(BOLD + CYAN + "│" + f" CHOOSE TIMEFRAME RESOLUTION ".center(50) + "│" + RESET)
        print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
        
        sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
        for idx, res in enumerate(sorted_resolutions, 1):
            line = f"  {idx}. {res} ({SUPPORTED_RESOLUTIONS[res]})"
            print(BOLD + CYAN + "│" + f"{line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
        
        res_choice = input(BOLD + "\nSelect resolution (1-8, Default 1d): " + RESET).strip()
        resolution = parse_resolution_input(res_choice, '1d')

        if symbol == "ALL":
            print(f"\n{CYAN}Fetching data for all assets...{RESET}")
            display_all_assets_dashboard(resolution)
            input(BOLD + "\nPress Enter to return to menu... " + RESET)
        else:
            opt_settings = load_optimized_settings()
            fast_period = 9
            slow_period = 21
            opt_key = f"{symbol}_{resolution}"
            if opt_key in opt_settings:
                fast_period = opt_settings[opt_key].get("fast_period", 9)
                slow_period = opt_settings[opt_key].get("slow_period", 21)
                
            # We fetch slow_period + 45 candles to let EMA crossover work and stabilize
            print(f"\n{CYAN}Fetching data for {symbol}...{RESET}")
            candles, err = fetch_candle_data(symbol, resolution, slow_period + 45)
            
            if err:
                display_dashboard(symbol, resolution, [], error_msg=err)
                input(BOLD + "\nPress Enter to return to menu... " + RESET)
            else:
                while True:
                    # Clear screen and display basic summary only
                    display_dashboard(symbol, resolution, candles, show_candles=False, fast_period=fast_period, slow_period=slow_period)
                    
                    print(BOLD + MAGENTA + "Analysis Options:" + RESET)
                    print("  [C] View Candlestick Chart & History Table")
                    print("  [E] View EMA Crossover Stop-and-Reverse (SAR) Analysis")
                    print("  [B] Back to Main Menu")
                    
                    sub_choice = input(BOLD + "\nSelect choice (C/E/B, Default B): " + RESET).strip().upper()
                    if sub_choice == 'C':
                        display_dashboard(symbol, resolution, candles, show_candles=True, fast_period=fast_period, slow_period=slow_period)
                        input(BOLD + "\nPress Enter to go back... " + RESET)
                    elif sub_choice == 'E':
                        clear_screen()
                        analyze_ema_crossover(candles, fast_period, slow_period)
                        input(BOLD + "\nPress Enter to go back... " + RESET)
                    else:
                        break

# CLI and Interactive selection entry points

def main():
    try:
        with open("debug_startup.log", "a") as f_dbg:
            f_dbg.write(f"[{datetime.now()}] Child main execution started. argv: {sys.argv}\n")
    except Exception:
        pass

    # Handle internal daemon redirection before argparse
    if "--daemon-runner" in sys.argv:
        sys.argv.remove("--daemon-runner")
        try:
            log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
            log_file = open(log_path, "a", encoding="utf-8", buffering=1)
            sys.stdout = log_file
            sys.stderr = log_file
        except Exception as e:
            try:
                with open("redirection_err.log", "w") as f_err:
                    import traceback
                    traceback.print_exc(file=f_err)
            except Exception:
                pass

    load_env()
    parser = argparse.ArgumentParser(description="Fetch and monitor candles from Delta Exchange in CMD.")
    parser.add_argument('-s', '--symbol', type=str, help="Delta Exchange trading symbol (e.g. SPYXUSD, QQQXUSD, XAUTUSD, SOLUSD, XRPUSD) or 'ALL' to show all")
    parser.add_argument('-r', '--resolution', type=str, default='1d', choices=list(SUPPORTED_RESOLUTIONS.keys()), help='Candle resolution timeframe (default: 1d)')
    parser.add_argument('-c', '--candles', type=int, default=15, help='Number of candles to load and display (default: 15)')
    parser.add_argument('--show-candles', action='store_true', help='Show candlestick chart and history table for single symbols')
    parser.add_argument('--ema-analysis', action='store_true', help='Run EMA Crossover Stop and Reverse analysis')
    parser.add_argument('--monitor', action='store_true', help='Start live monitoring and crossover alerting')
    parser.add_argument('--poll-interval', type=int, default=15, help='Polling interval in seconds for live monitoring (default: 15)')
    parser.add_argument('--account-info', action='store_true', help='Show account balances and open positions')
    parser.add_argument('--trade', action='store_true', help='Execute trades automatically on crossovers (requires credentials)')
    parser.add_argument('--trade-size', type=int, default=1, help='Order quantity/size for executed trades (default: 1)')
    parser.add_argument('--start', action='store_true', help='Start bot in background mode')
    parser.add_argument('--stop', action='store_true', help='Stop running background bot')
    parser.add_argument('--status', action='store_true', help='Check background bot status and print logs')
    parser.add_argument('--optimize', action='store_true', help='Run Genetic Algorithm to optimize EMA settings')
    parser.add_argument('--opt-generations', type=int, default=10, help='Generations for optimizer (default: 10)')
    parser.add_argument('--meta-optimize', action='store_true', help='Run Meta Genetic Algorithm to tune hyperparameters first')
    parser.add_argument('--meta-generations', type=int, default=5, help='Generations for meta optimizer (default: 5)')
    parser.add_argument('--meta-pop-size', type=int, default=10, help='Population size for meta optimizer (default: 10)')
    
    args = parser.parse_args()

    # 1. Background Daemon Controls
    if args.stop:
        stop_daemon()
        sys.exit(0)
        
    if args.status:
        check_daemon_status()
        sys.exit(0)
        
    if args.start:
        clean_args = [arg for arg in sys.argv[1:] if arg not in ["--start", "--stop", "--status"]]
        start_daemon(clean_args)
        time.sleep(1)
        os._exit(0)

    # 2. Strategy Optimization
    if args.optimize or args.meta_optimize:
        if not args.symbol or args.symbol.upper() == 'ALL':
            print(f"{RED}Error: You must specify a single specific symbol (e.g. -s SOLUSD) to run optimization.{RESET}")
            sys.exit(1)
        if args.meta_optimize:
            run_meta_genetic_optimization(args.symbol.upper(), args.resolution, args.meta_generations, args.meta_pop_size)
        else:
            run_genetic_optimization(args.symbol.upper(), args.resolution, args.opt_generations)
        sys.exit(0)

    if args.account_info:
        fetch_and_show_account()
        sys.exit(0)

    if args.symbol:
        symbol = args.symbol.upper()
        if args.monitor:
            # Monitor all, comma-separated, or specific symbol
            if symbol == 'ALL':
                symbols = [PRECONFIGURED_ASSETS[k]['symbol'] for k in sorted(PRECONFIGURED_ASSETS.keys(), key=int)]
            elif ',' in symbol:
                symbols = [s.strip() for s in symbol.split(',') if s.strip()]
            else:
                symbols = [symbol]
            run_live_monitor(symbols, args.resolution, args.poll_interval, trade=args.trade, trade_size=args.trade_size)
        elif symbol == 'ALL':
            print(f"Fetching data for all assets ({args.resolution})...")
            display_all_assets_dashboard(args.resolution)
        else:
            opt_settings = load_optimized_settings()
            fast_period = 9
            slow_period = 21
            opt_key = f"{symbol}_{args.resolution}"
            if opt_key in opt_settings:
                fast_period = opt_settings[opt_key].get("fast_period", 9)
                slow_period = opt_settings[opt_key].get("slow_period", 21)

            print(f"Fetching data for {symbol} ({args.resolution})...")
            fetch_count = max(slow_period + 45, args.candles) if args.ema_analysis else args.candles
            candles, err = fetch_candle_data(symbol, args.resolution, fetch_count)
            if err:
                display_dashboard(symbol, args.resolution, [], error_msg=err)
                sys.exit(1)
            else:
                display_dashboard(
                    symbol, 
                    args.resolution, 
                    candles, 
                    show_candles=args.show_candles, 
                    show_ema_analysis=args.ema_analysis,
                    fast_period=fast_period,
                    slow_period=slow_period
                )
    else:
        try:
            interactive_mode()
        except KeyboardInterrupt:
            print("\nExiting. Goodbye!")
            sys.exit(0)

if __name__ == "__main__":
    main()
