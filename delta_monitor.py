#!/usr/bin/env python3
"""
Delta Exchange Asset Monitor
Fetches OHLCV candle data from Delta Exchange V2 API and displays
a beautiful text-based candlestick chart and data table in the terminal.
Supports S&P 500, Nasdaq, Gold, Silver, Solana, XRP, and custom symbols.
"""

import sys
import math
import statistics
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
    '7': {'name': 'Bitcoin (BTCUSD)', 'symbol': 'BTCUSD', 'category': 'Cryptocurrency'},
    '8': {'name': 'Ethereum (ETHUSD)', 'symbol': 'ETHUSD', 'category': 'Cryptocurrency'},
    '9': {'name': 'Binance Coin (BNBUSD)', 'symbol': 'BNBUSD', 'category': 'Cryptocurrency'},
    '10': {'name': 'Dogecoin (DOGEUSD)', 'symbol': 'DOGEUSD', 'category': 'Cryptocurrency'},
    '11': {'name': 'Pepe (PEPEUSD)', 'symbol': 'PEPEUSD', 'category': 'Cryptocurrency'},
    '12': {'name': 'Avalanche (AVAXUSD)', 'symbol': 'AVAXUSD', 'category': 'Cryptocurrency'},
    '13': {'name': 'Sui (SUIUSD)', 'symbol': 'SUIUSD', 'category': 'Cryptocurrency'},
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
    
    # Open log file to redirect output
    log_file_handle = subprocess.DEVNULL
    try:
        log_file_handle = open("bot.log", "a", encoding="utf-8")
        log_file_handle.write(f"\n--- Spawning background bot process at {datetime.now()} ---\n")
        log_file_handle.write(f"Command: {cmd}\n")
        log_file_handle.flush()
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
        close_fds=True,
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


def print_finalized_report(symbol, best_res, best_fast, best_slow, best_session, best_macro, best_tp, best_sl, best_pyr, tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe, te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe, twin_sym, twin_p, twin_dd):
    print("\n" + BOLD + CYAN + "╔" + "═"*78 + "╗" + RESET)
    print(BOLD + CYAN + "║" + " FINALIZED STRATEGY REPORT ".center(78) + "║" + RESET)
    print(BOLD + CYAN + "╠" + "═"*78 + "╣" + RESET)
    print(BOLD + CYAN + f"║ Asset: {symbol:<15} Timeframe: {best_res:<10} Session: {best_session:<21} ║" + RESET)
    print(BOLD + CYAN + "╠" + "═"*78 + "╣" + RESET)
    print(BOLD + CYAN + "║" + " STRATEGY DNA (HYPERPARAMETERS) ".center(78) + "║" + RESET)
    print(BOLD + CYAN + "╟" + "─"*78 + "╢" + RESET)
    print(BOLD + CYAN + f"║ Fast EMA: {best_fast:<13} Slow EMA: {best_slow:<13} Macro Trend Filter: {best_macro}x      ║" + RESET)
    print(BOLD + CYAN + f"║ Take Profit (ATR): {best_tp:<4} Stop Loss (ATR): {best_sl:<4} Max Pyramiding Layers: {best_pyr:<2}  ║" + RESET)
    print(BOLD + CYAN + "╠" + "═"*78 + "╣" + RESET)
    print(BOLD + CYAN + "║" + " PERFORMANCE METRICS (IN-SAMPLE) ".center(78) + "║" + RESET)
    print(BOLD + CYAN + "╟" + "─"*78 + "╢" + RESET)
    print(BOLD + CYAN + f"║ Net Return: {tr_p:+.2f}%".ljust(41) + f"Max Drawdown: {tr_dd:.2f}%".ljust(39) + "║" + RESET)
    print(BOLD + CYAN + f"║ Win Rate:   {tr_wr*100:.1f}%".ljust(41) + f"Profit Factor: {tr_pf:.2f}".ljust(39) + "║" + RESET)
    print(BOLD + CYAN + f"║ Total Trades: {tr_tr}".ljust(41) + f"Sharpe Ratio:  {tr_sharpe:.2f}".ljust(39) + "║" + RESET)
    print(BOLD + CYAN + "╠" + "═"*78 + "╣" + RESET)
    print(BOLD + CYAN + "║" + " PERFORMANCE METRICS (OUT-OF-SAMPLE) ".center(78) + "║" + RESET)
    print(BOLD + CYAN + "╟" + "─"*78 + "╢" + RESET)
    
    oos_color = GREEN if te_p > 0 else RED
    print(BOLD + oos_color + f"║ Net Return: {te_p:+.2f}%".ljust(41 + len(BOLD+oos_color)) + f"Max Drawdown: {te_dd:.2f}%".ljust(39) + "║" + RESET)
    print(BOLD + oos_color + f"║ Win Rate:   {te_wr*100:.1f}%".ljust(41 + len(BOLD+oos_color)) + f"Profit Factor: {te_pf:.2f}".ljust(39) + "║" + RESET)
    print(BOLD + oos_color + f"║ Total Trades: {te_tr}".ljust(41 + len(BOLD+oos_color)) + f"Sharpe Ratio:  {te_sharpe:.2f}".ljust(39) + "║" + RESET)
    print(BOLD + CYAN + "╠" + "═"*78 + "╣" + RESET)
    print(BOLD + CYAN + "║" + " CROSS-ASSET VALIDATION ".center(78) + "║" + RESET)
    print(BOLD + CYAN + "╟" + "─"*78 + "╢" + RESET)
    if twin_sym:
        val_color = GREEN if twin_p > 0 else RED
        print(BOLD + val_color + f"║ Validated on: {twin_sym:<10} Return: {twin_p:+.2f}%   Drawdown: {twin_dd:.2f}%".ljust(79 + len(BOLD+val_color)) + "║" + RESET)
    else:
        print(BOLD + YELLOW + f"║ No correlated twin asset available for cross-validation.".ljust(87) + "║" + RESET)
    print(BOLD + CYAN + "╚" + "═"*78 + "╝\\n" + RESET)

def save_optimized_settings(symbol, resolution, fast_period, slow_period, session_name='24_7', macro_multiplier=4, ensemble=None, tp_mult=0.0, sl_mult=2.0, pyramid_max=3):
    """Saves optimized settings for a symbol and resolution to optimized_settings.json."""
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "optimized_settings.json")
    settings = load_optimized_settings()
    
    key = f"{symbol}_{resolution}"
    settings[key] = {
        "fast_period": fast_period,
        "slow_period": slow_period,
        "session_name": session_name,
        "macro_multiplier": macro_multiplier,
        "take_profit_mult": tp_mult,
        "stop_loss_mult": sl_mult,
        "pyramiding_max": pyramid_max,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # Also save a symbol-level fallback entry representing the absolute best settings found and the ensemble
    key_symbol = symbol
    settings[key_symbol] = {
        "resolution": resolution,
        "fast_period": fast_period,
        "slow_period": slow_period,
        "session_name": session_name,
        "macro_multiplier": macro_multiplier,
        "take_profit_mult": tp_mult,
        "stop_loss_mult": sl_mult,
        "pyramiding_max": pyramid_max,
        "ensemble": ensemble or [
            {
                "resolution": resolution,
                "fast_period": fast_period,
                "slow_period": slow_period,
                "session_name": session_name,
                "macro_multiplier": macro_multiplier,
        "take_profit_mult": tp_mult,
        "stop_loss_mult": sl_mult,
        "pyramiding_max": pyramid_max
            }
        ],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        print(f"{GREEN}Settings saved to optimized_settings.json successfully!{RESET}")
    except Exception as e:
        print(f"{RED}Error saving optimized settings: {e}{RESET}")

def backtest_ema_crossover(candles, fast_period, slow_period, tp_mult=0.0, sl_mult=2.0, pyramid_max=3, start_eval_idx=None, end_eval_idx=None, session_name='24_7', macro_multiplier=4):
    """
    Simulates Advanced Trend Following with GA-tunable variables:
    - MTF Trend Filtering (Macro EMA)
    - ATR Trailing Stops (sl_mult)
    - Take Profit targets (tp_mult)
    - Pyramiding (pyramid_max)
    """
    if len(candles) < slow_period + 5:
        return 0.0, 100.0, 0, 0.0, 0.0
        
    closes = [c['close'] for c in candles]
    fast_ema = calculate_ema(closes, fast_period)
    slow_ema = calculate_ema(closes, slow_period)
    if macro_multiplier > 0:
        macro_ema = calculate_ema(closes, slow_period * macro_multiplier)
    else:
        macro_ema = [None] * len(closes)
    atr = calculate_atr(candles, 14)
    
    if len(fast_ema) < len(closes) or fast_ema[-1] is None or slow_ema[-1] is None:
        return 0.0, 100.0, 0, 0.0, 0.0
        
    initial_equity = 10000.0
    equity = initial_equity
    equity_curve = [equity]
    
    warmup_idx = slow_period
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
    take_profit = 0.0
    highest_price = 0.0
    lowest_price = 0.0
    pyramid_count = 0
    avg_price = 0.0
    
    base_risk = 0.02
    position_size_dollars = 0.0
    
    for i in range(warmup_idx, end_eval_idx):
        curr_close = closes[i]
        prev_close = closes[i-1]
        
        curr_fast = fast_ema[i]
        curr_slow = slow_ema[i]
        curr_macro = macro_ema[i]
        curr_atr = atr[i]
        
        if curr_fast is None or curr_slow is None or curr_atr == 0:
            continue
            
        if position == 1:
            if i >= start_eval_idx:
                bar_return = (curr_close - prev_close) / prev_close
                equity += position_size_dollars * bar_return
            
            if curr_close > highest_price:
                highest_price = curr_close
                new_stop = highest_price - (curr_atr * sl_mult)
                if new_stop > stop_loss:
                    stop_loss = new_stop
                    
            if curr_close > avg_price + (curr_atr * 1.5) and pyramid_count < pyramid_max:
                pyramid_count += 1
                if i >= start_eval_idx:
                    position_size_dollars += equity * (base_risk / 2)
                avg_price = (avg_price + curr_close) / 2
                if tp_mult > 0:
                    take_profit = avg_price + (curr_atr * tp_mult)
                
            if curr_close <= stop_loss or (tp_mult > 0 and curr_close >= take_profit) or curr_fast < curr_slow:
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
                new_stop = lowest_price + (curr_atr * sl_mult)
                if new_stop < stop_loss:
                    stop_loss = new_stop
                    
            if curr_close < avg_price - (curr_atr * 1.5) and pyramid_count < pyramid_max:
                pyramid_count += 1
                if i >= start_eval_idx:
                    position_size_dollars += equity * (base_risk / 2)
                avg_price = (avg_price + curr_close) / 2
                if tp_mult > 0:
                    take_profit = avg_price - (curr_atr * tp_mult)
                
            if curr_close >= stop_loss or (tp_mult > 0 and curr_close <= take_profit) or curr_fast > curr_slow:
                if i >= start_eval_idx:
                    trade_return = (entry_price - curr_close) / entry_price
                    trade_returns.append(trade_return)
                    trades_count += 1
                position = 0
                
        if position == 0:
            if i >= start_eval_idx:
                equity_curve.append(equity)
            
            is_valid_time = True
            if session_name != '24_7':
                curr_min = (int(candles[i]['time']) // 60) % 1440
                if session_name == 'US':
                    is_valid_time = 810 <= curr_min <= 1200
                elif session_name == 'EU':
                    is_valid_time = 420 <= curr_min <= 930
                elif session_name == 'ASIA':
                    is_valid_time = 0 <= curr_min <= 510
                    
            if is_valid_time:
                if curr_fast > curr_slow and (curr_macro is None or curr_close > curr_macro):
                    position = 1
                    entry_price = curr_close
                    avg_price = curr_close
                    highest_price = curr_close
                    stop_loss = entry_price - (curr_atr * sl_mult)
                    if tp_mult > 0:
                        take_profit = entry_price + (curr_atr * tp_mult)
                    if i >= start_eval_idx:
                        position_size_dollars = equity * base_risk * 10
                    else:
                        position_size_dollars = 0.0
                    pyramid_count = 0
                    
                elif curr_fast < curr_slow and (curr_macro is None or curr_close < curr_macro):
                    position = -1
                    entry_price = curr_close
                    avg_price = curr_close
                    lowest_price = curr_close
                    stop_loss = entry_price + (curr_atr * sl_mult)
                    if tp_mult > 0:
                        take_profit = entry_price - (curr_atr * tp_mult)
                    if i >= start_eval_idx:
                        position_size_dollars = equity * base_risk * 10
                    else:
                        position_size_dollars = 0.0
                    pyramid_count = 0
                
    net_profit_pct = ((equity - initial_equity) / initial_equity) * 100.0
    
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
    
    
    sharpe_ratio = 0.0
    if len(trade_returns) > 1:
        stdev = statistics.stdev(trade_returns)
        if stdev > 0:
            mean_return = sum(trade_returns) / len(trade_returns)
            # Annualized approximation (trade based)
            sharpe_ratio = (mean_return / stdev) * math.sqrt(len(trade_returns))
    
    return net_profit_pct, max_dd, trades_count, win_rate, profit_factor, sharpe_ratio


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
        return 1500
    elif res_lower in ['1w']:
        return 500
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
    Runs an upgraded Genetic Algorithm to optimize EMA periods, timeframes, and sessions.
    Supports fallback retries with lower timeframes if validation fails.
    """
    print(BOLD + CYAN + f"\n=== Starting Multi-Parameter Strategy Optimization (GA V3) for {symbol} ===" + RESET)
    
    resolutions = ['5m', '15m', '30m', '1h', '4h', '1d']
    candles_by_res = {}
    
    print("Pre-fetching historical candles for all resolutions to avoid rate limits...")
    for res in resolutions:
        count = get_backtest_candle_count(res)
        print(f"  Fetching {res} (Count: {count})...")
        candles, err = fetch_candle_data(symbol, res, count)
        if not err and candles and len(candles) >= 40:
            candles_by_res[res] = candles
            print(f"    Loaded {len(candles)} candles.")
        else:
            print(f"    {YELLOW}Skip {res}: insufficient data ({err or 'empty'}){RESET}")
            
    if not candles_by_res:
        print(f"{RED}Error: Failed to fetch historical data for any timeframe resolution.{RESET}")
        return False
        
    # Start optimization with the requested resolution
    success = run_genetic_optimization_with_params(symbol, resolution, candles_by_res, generations, pop_size, elites_count, mutation_rate)
    
    if success:
        return True
        
    # Fallback retry loop downscaling the resolution to increase trade count / test sample size
    fallback_sequence = ['1d', '4h', '1h', '30m', '15m', '5m']
    if resolution in fallback_sequence:
        start_idx = fallback_sequence.index(resolution)
        # Try resolutions that are strictly lower/faster than the requested resolution
        for fallback_res in fallback_sequence[start_idx + 1:]:
            if fallback_res not in candles_by_res:
                continue
            print(BOLD + YELLOW + f"\n[OOS Failure Fallback] Retrying optimization for {symbol} with lower timeframe: {fallback_res} to increase sample size... {RESET}")
            success = run_genetic_optimization_with_params(symbol, fallback_res, candles_by_res, generations, pop_size, elites_count, mutation_rate)
            if success:
                print(BOLD + GREEN + f"[OOS Failure Fallback] Optimization succeeded on fallback resolution {fallback_res}!" + RESET)
                return True
                
    print(BOLD + RED + f"\n[Optimization Failure] All fallback resolutions failed Out-of-Sample validation for {symbol}." + RESET)
    return False

def run_genetic_optimization_inner(candles, resolution, generations, pop_size, elites_count, mutation_rate, tourn_size=3, mutation_scale=2, crossover_prob=0.7, fitness_dd_weight=0.5):
    """
    Inner GA worker function used by Meta-GA to evaluate hyperparameters.
    Uses 70/30 OOS holdout. Returns (best_chrom, blended_profit, blended_dd, blended_trades)
    where best_chrom = (fast, slow, res, session, macro_mult).
    """

    AVAILABLE_SESSIONS = ['24_7', 'US', 'EU', 'ASIA']
    AVAILABLE_MULTIPLIERS = [0, 2, 3, 4]
    AVAILABLE_TP_MULTS = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    AVAILABLE_SL_MULTS = [1.0, 2.0, 3.0, 4.0, 5.0]
    AVAILABLE_PYRAMIDS = [1, 2, 3, 4, 5]

    # Build a single-resolution candles_by_res dict so the same crossover/mutation
    # logic used in run_genetic_optimization_with_params works here too.
    candles_by_res = {resolution: candles}

    fast_range, slow_range = get_ema_ranges(resolution)

    # Calculate max unique configs (fast × slow × session × macro)
    max_ema_pairs = sum(
        1 for f in range(fast_range[0], fast_range[1] + 1)
        for s in range(max(slow_range[0], f + 10), slow_range[1] + 1)
    )
    max_possible = max_ema_pairs * len(AVAILABLE_SESSIONS) * len(AVAILABLE_MULTIPLIERS) * len(AVAILABLE_TP_MULTS) * len(AVAILABLE_SL_MULTS) * len(AVAILABLE_PYRAMIDS)
    eff_pop_size = min(pop_size, max(10, max_possible))

    population = []
    seen = set()
    attempts = 0
    while len(population) < eff_pop_size and attempts < eff_pop_size * 20:
        attempts += 1
        fast = random.randint(fast_range[0], fast_range[1])
        slow = random.randint(max(slow_range[0], fast + 10), slow_range[1])
        session = random.choice(AVAILABLE_SESSIONS)
        macro_mult = random.choice(AVAILABLE_MULTIPLIERS)
        tp = random.choice(AVAILABLE_TP_MULTS)
        sl = random.choice(AVAILABLE_SL_MULTS)
        pyr = random.choice(AVAILABLE_PYRAMIDS)
        chromosome = (fast, slow, resolution, session, macro_mult, tp, sl, pyr)
        if chromosome not in seen:
            seen.add(chromosome)
            population.append(chromosome)

    best_global_fit = -9999.0
    stagnant_gens = 0
    tourn_size = max(2, min(tourn_size, eff_pop_size // 2))

    for gen in range(1, generations + 1):
        scored_pop = []
        for fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max in population:
            c = candles_by_res.get(res, candles)
            split_idx_train = int(len(c) * 0.6)
            profit, max_dd, trades, win_rate, profit_factor, sharpe = backtest_ema_crossover(
                c, fast, slow, tp_mult=tp_mult, sl_mult=sl_mult, pyramid_max=pyramid_max, end_eval_idx=split_idx_train, session_name=session, macro_multiplier=macro_mult
            )
            calmar = profit / max_dd if max_dd > 0 else profit
            fitness = (sharpe * 2.0) + calmar + (profit_factor * win_rate * math.log1p(trades))
            if trades < 5:
                fitness -= 200.0
            scored_pop.append((fitness, (fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max), profit, max_dd, trades))

        scored_pop.sort(key=lambda x: x[0], reverse=True)
        best_fit = scored_pop[0][0]

        if best_fit > best_global_fit + 0.01:
            best_global_fit = best_fit
            stagnant_gens = 0
        else:
            stagnant_gens += 1
            if stagnant_gens >= 5 and gen > generations // 2:
                break

        # Elitism
        next_pop = []
        seen = set()
        for fit, chromosome, p, dd, tr in scored_pop:
            if chromosome not in seen:
                seen.add(chromosome)
                next_pop.append(chromosome)
                if len(next_pop) >= elites_count:
                    break

        current_mut_rate = mutation_rate * (1.0 - (gen / generations) * 0.5)

        # Crossover + mutation to fill next generation
        while len(next_pop) < eff_pop_size:
            candidates1 = random.sample(scored_pop, min(tourn_size, len(scored_pop)))
            candidates2 = random.sample(scored_pop, min(tourn_size, len(scored_pop)))
            p1 = max(candidates1, key=lambda x: x[0])[1]
            p2 = max(candidates2, key=lambda x: x[0])[1]

            if random.random() < crossover_prob:
                child_res = random.choice([p1[2], p2[2]])
                child_session = random.choice([p1[3], p2[3]])
                child_macro = random.choice([p1[4], p2[4]])
                child_tp = random.choice([p1[5], p2[5]])
                child_sl = random.choice([p1[6], p2[6]])
                child_pyr = random.choice([p1[7], p2[7]])
                fr, sr = get_ema_ranges(child_res)
                child_fast = max(fr[0], min(fr[1], int((p1[0] + p2[0]) / 2) + random.randint(-max(1, mutation_scale // 2), max(1, mutation_scale // 2))))
                child_slow = max(max(sr[0], child_fast + 10), min(sr[1], int((p1[1] + p2[1]) / 2) + random.randint(-mutation_scale, mutation_scale)))
            else:
                child_res = p1[2]
                child_session = p1[3]
                child_macro = p1[4]
                child_tp = p1[5]
                child_sl = p1[6]
                child_pyr = p1[7]
                child_fast = p1[0]
                child_slow = p1[1]
                fr, sr = get_ema_ranges(child_res)

            if random.random() < current_mut_rate:
                child_res = random.choice(list(candles_by_res.keys()))
                fr, sr = get_ema_ranges(child_res)
            if random.random() < current_mut_rate:
                child_session = random.choice(AVAILABLE_SESSIONS)
            if random.random() < current_mut_rate:
                child_macro = random.choice(AVAILABLE_MULTIPLIERS)
            if random.random() < current_mut_rate:
                child_tp = random.choice(AVAILABLE_TP_MULTS)
            if random.random() < current_mut_rate:
                child_sl = random.choice(AVAILABLE_SL_MULTS)
            if random.random() < current_mut_rate:
                child_pyr = random.choice(AVAILABLE_PYRAMIDS)
            if random.random() < current_mut_rate:
                child_fast = max(fr[0], min(fr[1], child_fast + random.randint(-mutation_scale, mutation_scale)))
            if random.random() < current_mut_rate:
                child_slow = max(max(slow_range[0], child_fast + 10), min(slow_range[1], child_slow + random.randint(-mutation_scale * 2, mutation_scale * 2)))

            chromosome = (child_fast, child_slow, child_res, child_session, child_macro, child_tp, child_sl, child_pyr)
            if chromosome not in seen:
                seen.add(chromosome)
                next_pop.append(chromosome)
            else:
                # Attempt escape mutation
                added = False
                for _ in range(20):
                    m_fast = max(fr[0], min(fr[1], child_fast + random.randint(-mutation_scale - 1, mutation_scale + 1)))
                    m_slow = max(max(sr[0], m_fast + 10), min(sr[1], child_slow + random.randint(-mutation_scale * 2 - 1, mutation_scale * 2 + 1)))
                    m_res = random.choice(list(candles_by_res.keys())) if random.random() < 0.3 else child_res
                    m_session = random.choice(AVAILABLE_SESSIONS) if random.random() < 0.3 else child_session
                    m_macro = random.choice(AVAILABLE_MULTIPLIERS) if random.random() < 0.3 else child_macro
                    m_tp = random.choice(AVAILABLE_TP_MULTS) if random.random() < 0.3 else child_tp
                    m_sl = random.choice(AVAILABLE_SL_MULTS) if random.random() < 0.3 else child_sl
                    m_pyr = random.choice(AVAILABLE_PYRAMIDS) if random.random() < 0.3 else child_pyr
                    m_chrom = (m_fast, m_slow, m_res, m_session, m_macro, m_tp, m_sl, m_pyr)
                    if m_chrom not in seen:
                        seen.add(m_chrom)
                        next_pop.append(m_chrom)
                        added = True
                        break
                if not added:
                    next_pop.append(chromosome)  # allow duplicate rather than infinite loop

        population = next_pop

    # Validation & OOS Scoring (True Holdout)
    final_scored = []
    for fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max in population:
        c = candles_by_res.get(res, candles)
        split_idx_train = int(len(c) * 0.70)

        # Train on 70%
        tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe = backtest_ema_crossover(
            c, fast, slow, tp_mult=tp_mult, sl_mult=sl_mult, pyramid_max=pyramid_max, end_eval_idx=split_idx_train, session_name=session, macro_multiplier=macro_mult
        )
        tr_calmar = tr_p / tr_dd if tr_dd > 0 else tr_p
        train_fitness = (tr_sharpe * 2.0) + tr_calmar + (tr_pf * tr_wr * math.log1p(tr_tr))
        if tr_tr < 10:
            train_fitness -= 200.0

        # Out-of-Sample Holdout (30%)
        te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe = backtest_ema_crossover(
            c, fast, slow, tp_mult=tp_mult, sl_mult=sl_mult, pyramid_max=pyramid_max, start_eval_idx=split_idx_train, session_name=session, macro_multiplier=macro_mult
        )

        final_scored.append((train_fitness, (fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max), tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe, te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe))

    final_scored.sort(key=lambda x: x[0], reverse=True)
    best_fitness, best_chrom, tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe, te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe = final_scored[0]

    # Return test metrics to prioritize out-of-sample robustness
    return best_chrom, te_p, te_dd, te_tr

def run_genetic_optimization_with_params(symbol, resolution, candles_input, generations, pop_size, elites_count, mutation_rate, tourn_size=3, mutation_scale=2, crossover_prob=0.7, fitness_dd_weight=0.5):
    """
    Runs final strategy optimization with custom parameters and saves settings.
    Now uses 70/30 Out-of-Sample Holdout testing to prove edge.
    """
    import math
    if isinstance(candles_input, dict):
        candles_by_res = candles_input
    else:
        candles_by_res = {resolution: candles_input}
        
    AVAILABLE_SESSIONS = ['24_7', 'US', 'EU', 'ASIA']
    AVAILABLE_MULTIPLIERS = [0, 2, 3, 4]
    AVAILABLE_TP_MULTS = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    AVAILABLE_SL_MULTS = [1.0, 2.0, 3.0, 4.0, 5.0]
    AVAILABLE_PYRAMIDS = [1, 2, 3, 4, 5]
    
    # Calculate maximum possible unique configurations
    max_possible = 0
    for res in candles_by_res.keys():
        fast_range, slow_range = get_ema_ranges(res)
        for f in range(fast_range[0], fast_range[1] + 1):
            for s in range(max(slow_range[0], f + 10), slow_range[1] + 1):
                max_possible += 16 * 6 * 5 * 5
                
    eff_pop_size = min(pop_size, max_possible)
    
    population = []
    seen = set()
    attempts = 0
    while len(population) < eff_pop_size and attempts < eff_pop_size * 30:
        attempts += 1
        res = random.choice(list(candles_by_res.keys()))
        session = random.choice(AVAILABLE_SESSIONS)
        macro_mult = random.choice(AVAILABLE_MULTIPLIERS)
        tp = random.choice(AVAILABLE_TP_MULTS)
        sl = random.choice(AVAILABLE_SL_MULTS)
        pyr = random.choice(AVAILABLE_PYRAMIDS)
        fast_range, slow_range = get_ema_ranges(res)
        fast = random.randint(fast_range[0], fast_range[1])
        slow = random.randint(max(slow_range[0], fast + 10), slow_range[1])

        chromosome = (fast, slow, res, session, macro_mult, tp, sl, pyr)
        if chromosome not in seen:
            seen.add(chromosome)
            population.append(chromosome)
    
    if not population:
        print(f"{RED}Error: Could not generate initial population. Check EMA ranges.{RESET}")
        return False
    eff_pop_size = len(population)  # Clamp to what we actually got
        
    best_global_fit = -9999.0
    stagnant_gens = 0
    tourn_size = max(2, min(tourn_size, eff_pop_size // 2))
    
    print(f"Evolving populations over {generations} generations...")
    for gen in range(1, generations + 1):
        scored_pop = []
        for fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max in population:
            candles = candles_by_res[res]
            split_idx_train = int(len(candles) * 0.6)
            profit, max_dd, trades, win_rate, profit_factor, sharpe = backtest_ema_crossover(
                candles, fast, slow, tp_mult=tp_mult, sl_mult=sl_mult, pyramid_max=pyramid_max, end_eval_idx=split_idx_train, session_name=session, macro_multiplier=macro_mult
            )
            # Sharpe-expectancy normalized fitness formula
            calmar = profit / max_dd if max_dd > 0 else profit
            fitness = (sharpe * 2.0) + calmar + (profit_factor * win_rate * math.log1p(trades))
            if trades < 5:
                fitness -= 200.0
            scored_pop.append((fitness, (fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max), profit, max_dd, trades))
            
        scored_pop.sort(key=lambda x: x[0], reverse=True)
        best_fit, best_chrom, best_p, best_dd, best_tr = scored_pop[0]
        best_fast, best_slow, best_res, best_session, best_macro, best_tp, best_sl, best_pyr = best_chrom
        
        print(f"  Gen {gen:2d}/{generations:2d} | Best Strategy: TF {best_res:<3} | Session {best_session:<5} | EMA {best_fast:2d}/{best_slow:3d} (Macro Mult: {best_macro}) | TP: {best_tp} | SL: {best_sl} | Pyr: {best_pyr} | "
              f"Train Return: {best_p:+.2f}% | Max DD: {best_dd:.2f}% | Trades: {best_tr}")
              
        if best_fit > best_global_fit + 0.01:
            best_global_fit = best_fit
            stagnant_gens = 0
        else:
            stagnant_gens += 1
            if stagnant_gens >= 5 and gen > generations // 2:
                print(f"  {YELLOW}Early stopping triggered (No improvement for 5 generations){RESET}")
                break
              
        # Next generation with uniqueness check
        next_pop = []
        seen = set()
        for fit, chromosome, p, dd, tr in scored_pop:
            if chromosome not in seen:
                seen.add(chromosome)
                next_pop.append(chromosome)
                if len(next_pop) >= elites_count:
                    break
                    
        current_mut_rate = mutation_rate * (1.0 - (gen / generations) * 0.5)
        
        while len(next_pop) < eff_pop_size:
            sample_k = min(tourn_size, len(scored_pop))
            p1 = max(random.sample(scored_pop, sample_k), key=lambda x: x[0])[1]
            p2 = max(random.sample(scored_pop, sample_k), key=lambda x: x[0])[1]
            
            # Blend Crossover & Discrete Crossover
            if random.random() < crossover_prob:
                child_res = random.choice([p1[2], p2[2]])
                if child_res not in candles_by_res:
                    child_res = list(candles_by_res.keys())[0]
                child_session = random.choice([p1[3], p2[3]])
                child_macro = random.choice([p1[4], p2[4]])
                child_tp = random.choice([p1[5], p2[5]])
                child_sl = random.choice([p1[6], p2[6]])
                child_pyr = random.choice([p1[7], p2[7]])
                child_fast = int((p1[0] + p2[0]) / 2) + random.randint(-max(1, mutation_scale // 2), max(1, mutation_scale // 2))
                child_slow = int((p1[1] + p2[1]) / 2) + random.randint(-mutation_scale, mutation_scale)
            else:
                child_res = p1[2]
                child_session = p1[3]
                child_macro = p1[4]
                child_tp = p1[5]
                child_sl = p1[6]
                child_pyr = p1[7]
                child_fast = p1[0]
                child_slow = p1[1]
            
            fast_range, slow_range = get_ema_ranges(child_res)
            child_fast = max(fast_range[0], min(fast_range[1], child_fast))
            child_slow = max(max(slow_range[0], child_fast + 10), min(slow_range[1], child_slow))
            
            # Apply Mutation
            if random.random() < current_mut_rate:
                child_res = random.choice(list(candles_by_res.keys()))
                fast_range, slow_range = get_ema_ranges(child_res)
            if random.random() < current_mut_rate:
                child_session = random.choice(AVAILABLE_SESSIONS)
            if random.random() < current_mut_rate:
                child_macro = random.choice(AVAILABLE_MULTIPLIERS)
            if random.random() < current_mut_rate:
                child_tp = random.choice(AVAILABLE_TP_MULTS)
            if random.random() < current_mut_rate:
                child_sl = random.choice(AVAILABLE_SL_MULTS)
            if random.random() < current_mut_rate:
                child_pyr = random.choice(AVAILABLE_PYRAMIDS)
            if random.random() < current_mut_rate:
                child_fast = max(fast_range[0], min(fast_range[1], child_fast + random.randint(-mutation_scale, mutation_scale)))
            if random.random() < current_mut_rate:
                child_slow = max(max(slow_range[0], child_fast + 10), min(slow_range[1], child_slow + random.randint(-mutation_scale * 2, mutation_scale * 2)))
                
            chromosome = (child_fast, child_slow, child_res, child_session, child_macro, child_tp, child_sl, child_pyr)
            if chromosome not in seen:
                seen.add(chromosome)
                next_pop.append(chromosome)
            else:
                mutated = False
                for _ in range(15):
                    m_fast = max(fast_range[0], min(fast_range[1], child_fast + random.randint(-mutation_scale - 1, mutation_scale + 1)))
                    m_slow = max(max(slow_range[0], m_fast + 10), min(slow_range[1], child_slow + random.randint(-mutation_scale * 2 - 1, mutation_scale * 2 + 1)))
                    m_res = random.choice(list(candles_by_res.keys())) if random.random() < 0.3 else child_res
                    m_session = random.choice(AVAILABLE_SESSIONS) if random.random() < 0.3 else child_session
                    m_macro = random.choice(AVAILABLE_MULTIPLIERS) if random.random() < 0.3 else child_macro
                    m_tp = random.choice(AVAILABLE_TP_MULTS) if random.random() < 0.3 else child_tp
                    m_sl = random.choice(AVAILABLE_SL_MULTS) if random.random() < 0.3 else child_sl
                    m_pyr = random.choice(AVAILABLE_PYRAMIDS) if random.random() < 0.3 else child_pyr
                    m_config = (m_fast, m_slow, m_res, m_session, m_macro, m_tp, m_sl, m_pyr)
                    if m_config not in seen:
                        seen.add(m_config)
                        next_pop.append(m_config)
                        mutated = True
                        break
                if not mutated:
                    for _ in range(50):
                        r_res = random.choice(list(candles_by_res.keys()))
                        r_session = random.choice(AVAILABLE_SESSIONS)
                        r_macro = random.choice(AVAILABLE_MULTIPLIERS)
                        r_tp = random.choice(AVAILABLE_TP_MULTS)
                        r_sl = random.choice(AVAILABLE_SL_MULTS)
                        r_pyr = random.choice(AVAILABLE_PYRAMIDS)
                        r_fast_range, r_slow_range = get_ema_ranges(r_res)
                        r_fast = random.randint(r_fast_range[0], r_fast_range[1])
                        r_slow = random.randint(max(r_slow_range[0], r_fast + 10), r_slow_range[1])
                        r_config = (r_fast, r_slow, r_res, r_session, r_macro, r_tp, r_sl, r_pyr)
                        if r_config not in seen:
                            seen.add(r_config)
                            next_pop.append(r_config)
                            mutated = True
                            break
                if not mutated:
                    next_pop.append(chromosome)
            
        population = next_pop
        
    print(BOLD + CYAN + f"\nRunning Out-of-Sample (OOS) Validation..." + RESET)
    final_scored = []
    for fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max in population:
        candles = candles_by_res[res]
        split_idx_train = int(len(candles) * 0.70)
        
        # Train on 70%
        tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe = backtest_ema_crossover(
            candles, fast, slow, tp_mult=tp_mult, sl_mult=sl_mult, pyramid_max=pyramid_max, end_eval_idx=split_idx_train, session_name=session, macro_multiplier=macro_mult
        )
        tr_calmar = tr_p / tr_dd if tr_dd > 0 else tr_p
        train_fitness = (tr_sharpe * 2.0) + tr_calmar + (tr_pf * tr_wr * math.log1p(tr_tr))
        if tr_tr < 10:
            train_fitness -= 200.0
            
        final_fit = train_fitness
        
        # Out-of-Sample Holdout (30%) - evaluated for reporting but never used in final_fit selection
        te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe = backtest_ema_crossover(
            candles, fast, slow, tp_mult=tp_mult, sl_mult=sl_mult, pyramid_max=pyramid_max, start_eval_idx=split_idx_train, session_name=session, macro_multiplier=macro_mult
        )
        
        final_scored.append((final_fit, (fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max), tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe, te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe))
        
    final_scored.sort(key=lambda x: x[0], reverse=True)
    best_fitness, (best_fast, best_slow, best_res, best_session, best_macro, best_tp, best_sl, best_pyr), tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe, te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe = final_scored[0]
    
    # Extract top 3 unique configurations for ensemble
    top_ensemble = []
    seen_configs = set()
    for fit, chrom, itp, itd, itt, ivp, ivd, ivs, otp, otd, ott, ovp, ovd, ovs in final_scored:
        fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max = chrom
        config_key = (fast, slow, res, session, macro_mult, tp_mult, sl_mult, pyramid_max)
        if config_key not in seen_configs:
            seen_configs.add(config_key)
            top_ensemble.append({
                "resolution": res,
                "fast_period": fast,
                "slow_period": slow,
                "session_name": session,
                "macro_multiplier": macro_mult,
                "take_profit_mult": tp_mult,
                "stop_loss_mult": sl_mult,
                "pyramiding_max": pyramid_max
            })
            if len(top_ensemble) >= 3:
                break
                
    print(BOLD + GREEN + f"\nOptimization Complete!" + RESET)
    print(f"Optimal EMA Strategy: Fast {best_fast} / Slow {best_slow} on Timeframe: {best_res} | Session: {best_session} | Macro Mult: {best_macro} | TP: {best_tp} | SL: {best_sl} | Pyr: {best_pyr}")
    print(f"Training (In-Sample) Return:   {tr_p:+.2f}% | Max DD: {tr_dd:.2f}% | Trades: {tr_tr}")
    
    if te_p > 0:
        if tr_tr >= 15:
            print(f"{CYAN}--- Cross-Asset Validation ---{RESET}")
            # Find a correlated asset
            crypto_twins = {
                'BTCUSD': 'ETHUSD', 'ETHUSD': 'BTCUSD',
                'SOLUSD': 'AVAXUSD', 'AVAXUSD': 'SOLUSD',
                'DOGEUSD': 'PEPEUSD', 'PEPEUSD': 'DOGEUSD',
                'QQQXUSD': 'SPYXUSD', 'SPYXUSD': 'QQQXUSD',
                'XAUTUSD': 'SLVONUSD', 'SLVONUSD': 'XAUTUSD'
            }
            twin_sym = crypto_twins.get(symbol)
            cross_passed = True
            
            if twin_sym:
                print(f"Validating {symbol} strategy robustness against {twin_sym}...")
                c_cnt = get_backtest_candle_count(best_res)
                twin_candles, err = fetch_candle_data(twin_sym, best_res, c_cnt)
                if not err and twin_candles and len(twin_candles) >= 40:
                    twin_tr_p, twin_tr_dd, twin_tr_tr, twin_tr_wr, twin_tr_pf, twin_sharpe = backtest_ema_crossover(
                        twin_candles, best_fast, best_slow, tp_mult=best_tp, sl_mult=best_sl, pyramid_max=best_pyr, session_name=best_session, macro_multiplier=best_macro
                    )
                    if twin_tr_p > 0:
                        print(f"Cross-Asset Return on {twin_sym}: {BOLD}{GREEN}{twin_tr_p:+.2f}%{RESET} | Max DD: {twin_tr_dd:.2f}% | Trades: {twin_tr_tr}")
                    else:
                        print(f"Cross-Asset Return on {twin_sym}: {BOLD}{RED}{twin_tr_p:+.2f}% (FAILED){RESET} - Strategy is curve-fitted to {symbol}!")
                        cross_passed = False
                else:
                    print(f"Could not fetch {twin_sym} data, skipping cross-validation.")
            else:
                print(f"No twin asset mapping for {symbol}, skipping cross-validation.")
                
            if not cross_passed:
                print(f"{RED}Rejecting strategy due to Cross-Asset Validation failure.{RESET}")
                return False
                
            _twin_p = twin_tr_p if 'twin_tr_p' in dir() else 0.0
            _twin_dd = twin_tr_dd if 'twin_tr_dd' in dir() else 0.0
            print_finalized_report(symbol, best_res, best_fast, best_slow, best_session, best_macro, best_tp, best_sl, best_pyr, tr_p, tr_dd, tr_tr, tr_wr, tr_pf, tr_sharpe, te_p, te_dd, te_tr, te_wr, te_pf, te_sharpe, twin_sym, _twin_p, _twin_dd)
            save_optimized_settings(symbol, best_res, best_fast, best_slow, session_name=best_session, macro_multiplier=best_macro, ensemble=top_ensemble, tp_mult=best_tp, sl_mult=best_sl, pyramid_max=best_pyr)
            return True
        else:
            print(f"Testing (Out-of-Sample) Return: {BOLD}{YELLOW}{te_p:+.2f}% (Passed OOS but trade count {tr_tr} is under statistical threshold of 15){RESET} | Max DD: {te_dd:.2f}% | Trades: {te_tr}")
            print(f"{YELLOW}Skipping saving settings to optimized_settings.json to avoid small-sample overfitting.{RESET}")
            return False
    else:
        print(f"Testing (Out-of-Sample) Return: {BOLD}{RED}{te_p:+.2f}% (FAILED OOS){RESET} | Max DD: {te_dd:.2f}% | Trades: {te_tr}")
        print(f"{YELLOW}Skipping saving settings to optimized_settings.json because strategy failed Out-of-Sample validation.{RESET}")
        return False

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
    seen = set()
    while len(population) < meta_pop_size:
        pop_size = random.randint(50, 200)
        elites = max(1, min(int(pop_size * 0.15), random.randint(2, 8)))
        mut_rate = round(random.uniform(0.1, 0.4), 2)
        gens = random.randint(20, 100)
        tourn_size = random.randint(2, 6)
        mutation_scale = random.randint(1, 4)
        crossover_prob = round(random.uniform(0.4, 0.9), 2)
        fitness_dd_weight = round(random.uniform(0.1, 1.5), 2)
        config = (pop_size, elites, mut_rate, gens, tourn_size, mutation_scale, crossover_prob, fitness_dd_weight)
        if config not in seen:
            seen.add(config)
            population.append(config)
        
    best_global_fit = -9999.0
    stagnant_gens = 0
    meta_tourn_size = max(3, meta_pop_size // 4)
    
    print("Evolving GA hyperparameters...")
    for gen in range(1, meta_generations + 1):
        scored_pop = []
        for pop_size, elites, mut_rate, gens, tourn_size, mutation_scale, crossover_prob, fitness_dd_weight in population:
            runs_fitness = []
            for _ in range(2):
                best_chrom, profit, max_dd, trades = run_genetic_optimization_inner(
                    candles, resolution, gens, pop_size, elites, mut_rate, tourn_size, mutation_scale, crossover_prob, fitness_dd_weight
                )
                best_fast, best_slow, best_res, best_session, best_macro, best_tp, best_sl, best_pyr = best_chrom
                # Compute strategy fitness using same advanced formula
                _, _, _, win_rate, profit_factor, sharpe = backtest_ema_crossover(candles, best_fast, best_slow, tp_mult=best_tp, sl_mult=best_sl, pyramid_max=best_pyr, session_name=best_session, macro_multiplier=best_macro)
                calmar_m = profit / max_dd if max_dd > 0 else profit
                fitness = (sharpe * 2.0) + calmar_m + (profit_factor * win_rate * math.log1p(trades))
                if trades < 15:
                    fitness -= 200.0
                runs_fitness.append(fitness)
            avg_fitness = sum(runs_fitness) / len(runs_fitness)
            # Efficiency Penalty: penalize excessively large computational load
            efficiency_penalty = (pop_size * gens) * 0.05
            penalized_fitness = avg_fitness - efficiency_penalty
            scored_pop.append((penalized_fitness, (pop_size, elites, mut_rate, gens, tourn_size, mutation_scale, crossover_prob, fitness_dd_weight), avg_fitness))
            
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
        
        # Mating and breeding with uniqueness check
        elites_count = max(2, meta_pop_size // 4)
        next_pop = []
        seen = set()
        for pfit, params, rfit in scored_pop:
            if params not in seen:
                seen.add(params)
                next_pop.append(params)
                if len(next_pop) >= elites_count:
                    break
                    
        current_mut_rate = 0.25 * (1.0 - (gen / meta_generations) * 0.5)
        
        while len(next_pop) < meta_pop_size:
            pool = scored_pop[:max(3, meta_tourn_size)]
            if len(pool) < 2:
                pool = scored_pop  # fallback to full list
            parents = random.sample(pool, min(2, len(pool)))
            if len(parents) < 2:
                parents = [parents[0], parents[0]]
            p1, p2 = parents[0][1], parents[1][1]
            
            # Blend Crossover
            child_pop_size = max(50, min(200, int((p1[0] + p2[0]) / 2) + random.choice([-2, 0, 2])))
            child_elites = max(1, min(int(child_pop_size * 0.15), int((p1[1] + p2[1]) / 2) + random.choice([-1, 0, 1])))
            child_mut_rate = round((p1[2] + p2[2]) / 2 + random.choice([-0.05, 0.0, 0.05]), 2)
            child_gens = max(10, min(25, int((p1[3] + p2[3]) / 2) + random.choice([-1, 0, 1])))
            child_tourn = max(2, min(8, int((p1[4] + p2[4]) / 2) + random.choice([-1, 0, 1])))
            child_scale = max(1, min(4, int((p1[5] + p2[5]) / 2) + random.choice([-1, 0, 1])))
            child_cross = max(0.2, min(0.95, round((p1[6] + p2[6]) / 2 + random.choice([-0.05, 0.0, 0.05]), 2)))
            child_weight = max(0.05, min(2.0, round((p1[7] + p2[7]) / 2 + random.choice([-0.1, 0.0, 0.1]), 2)))
            
            # Mutation
            if random.random() < current_mut_rate:
                child_pop_size = max(50, min(200, child_pop_size + random.choice([-5, -2, 2, 5])))
            if random.random() < current_mut_rate:
                child_elites = max(1, min(int(child_pop_size * 0.15), child_elites + random.choice([-1, 1])))
            if random.random() < current_mut_rate:
                child_mut_rate = max(0.05, min(0.5, round(child_mut_rate + random.choice([-0.05, 0.05]), 2)))
            if random.random() < current_mut_rate:
                child_gens = max(10, min(100, child_gens + random.choice([-2, -1, 1, 2])))
            if random.random() < current_mut_rate:
                child_tourn = max(2, min(8, child_tourn + random.choice([-1, 1])))
            if random.random() < current_mut_rate:
                child_scale = max(1, min(4, child_scale + random.choice([-1, 1])))
            if random.random() < current_mut_rate:
                child_cross = max(0.2, min(0.95, round(child_cross + random.choice([-0.05, 0.05]), 2)))
            if random.random() < current_mut_rate:
                child_weight = max(0.05, min(2.0, round(child_weight + random.choice([-0.1, 0.1]), 2)))
                
            child_elites = max(1, min(int(child_pop_size * 0.15), child_elites))
                
            config = (child_pop_size, child_elites, child_mut_rate, child_gens, child_tourn, child_scale, child_cross, child_weight)
            if config not in seen:
                seen.add(config)
                next_pop.append(config)
            else:
                # Mutate to make it unique
                mutated = False
                for _ in range(15):
                    m_pop_size = max(50, min(200, child_pop_size + random.choice([-3, -1, 1, 3])))
                    m_elites = max(1, min(int(m_pop_size * 0.15), child_elites + random.choice([-1, 1])))
                    m_mut_rate = max(0.05, min(0.5, round(child_mut_rate + random.choice([-0.03, 0.03]), 2)))
                    m_gens = max(10, min(100, child_gens + random.choice([-2, -1, 1, 2])))
                    m_tourn = max(2, min(8, child_tourn + random.choice([-1, 1])))
                    m_scale = max(1, min(4, child_scale + random.choice([-1, 1])))
                    m_cross = max(0.2, min(0.95, round(child_cross + random.choice([-0.03, 0.03]), 2)))
                    m_weight = max(0.05, min(2.0, round(child_weight + random.choice([-0.05, 0.05]), 2)))
                    m_config = (m_pop_size, m_elites, m_mut_rate, m_gens, m_tourn, m_scale, m_cross, m_weight)
                    if m_config not in seen:
                        seen.add(m_config)
                        next_pop.append(m_config)
                        mutated = True
                        break
                if not mutated:
                    # Fallback to random search
                    for _ in range(50):
                        r_pop_size = random.randint(50, 200)
                        r_elites = max(1, min(int(r_pop_size * 0.15), random.randint(2, 8)))
                        r_mut_rate = round(random.uniform(0.1, 0.4), 2)
                        r_gens = random.randint(20, 100)
                        r_tourn = random.randint(2, 6)
                        r_scale = random.randint(1, 4)
                        r_cross = round(random.uniform(0.4, 0.9), 2)
                        r_weight = round(random.uniform(0.1, 1.5), 2)
                        r_config = (r_pop_size, r_elites, r_mut_rate, r_gens, r_tourn, r_scale, r_cross, r_weight)
                        if r_config not in seen:
                            seen.add(r_config)
                            next_pop.append(r_config)
                            mutated = True
                            break
                if not mutated:
                    next_pop.append(config)
            
        population = next_pop
        
    final_scored = []
    for pop_size, elites, mut_rate, gens, tourn_size, mutation_scale, crossover_prob, fitness_dd_weight in population:
        runs_fitness = []
        for _ in range(2):
            best_chrom, profit, max_dd, trades = run_genetic_optimization_inner(
                candles, resolution, gens, pop_size, elites, mut_rate, tourn_size, mutation_scale, crossover_prob, fitness_dd_weight
            )
            best_fast, best_slow, best_res, best_session, best_macro, best_tp, best_sl, best_pyr = best_chrom
            _, _, _, win_rate, profit_factor, sharpe = backtest_ema_crossover(candles, best_fast, best_slow, tp_mult=best_tp, sl_mult=best_sl, pyramid_max=best_pyr, session_name=best_session, macro_multiplier=best_macro)
            calmar_m = profit / max_dd if max_dd > 0 else profit
            fitness = (sharpe * 2.0) + calmar_m + (profit_factor * win_rate * math.log1p(trades))
            if trades < 15:
                fitness -= 200.0
            runs_fitness.append(fitness)
        avg_fitness = sum(runs_fitness) / len(runs_fitness)
        efficiency_penalty = (pop_size * gens) * 0.05
        penalized_fitness = avg_fitness - efficiency_penalty
        final_scored.append((penalized_fitness, (pop_size, elites, mut_rate, gens, tourn_size, mutation_scale, crossover_prob, fitness_dd_weight), avg_fitness))
        
    final_scored.sort(key=lambda x: x[0], reverse=True)
    best_penalized_fit, (best_pop_size, best_elites, best_mut_rate, best_gens, best_tourn, best_scale, best_cross, best_weight), best_avg_fit = final_scored[0]
    
    print(BOLD + GREEN + f"\nMeta-Optimization Complete!" + RESET)
    print(f"Optimal GA Configuration:")
    print(f"  Population Size: {best_pop_size}")
    print(f"  Elites Count:    {best_elites}")
    print(f"  Mutation Rate:   {best_mut_rate}")
    print(f"  Generations:     {best_gens}")
    print(f"  Tournament Size: {best_tourn}")
    print(f"  Mutation Scale:  {best_scale}")
    print(f"  Crossover Prob:  {best_cross:.2f}")
    print(f"  Drawdown Weight: {best_weight:.2f}")
    print(f"  Expected Avg Strategy Fitness: {best_avg_fit:+.2f} (Penalized: {best_penalized_fit:+.2f})")
    
    print(BOLD + CYAN + f"\nRunning final strategy optimization using tuned hyperparameters..." + RESET)
    resolutions = ['5m', '15m', '30m', '1h', '4h', '1d']
    candles_by_res = {}
    for res in resolutions:
        if res == resolution and not err and candles:
            candles_by_res[res] = candles
        else:
            c_cnt = get_backtest_candle_count(res)
            c_data, c_err = fetch_candle_data(symbol, res, c_cnt)
            if not c_err and c_data and len(c_data) >= 40:
                candles_by_res[res] = c_data
                
    success = run_genetic_optimization_with_params(symbol, resolution, candles_by_res, best_gens, best_pop_size, best_elites, best_mut_rate, best_tourn, best_scale, best_cross, best_weight)
    if not success:
        fallback_sequence = ['1d', '4h', '1h', '30m', '15m', '5m']
        if resolution in fallback_sequence:
            start_idx = fallback_sequence.index(resolution)
            for fallback_res in fallback_sequence[start_idx + 1:]:
                if fallback_res not in candles_by_res:
                    continue
                print(BOLD + YELLOW + f"\n[OOS Failure Fallback] Retrying final optimization for {symbol} with lower timeframe: {fallback_res}... {RESET}")
                success = run_genetic_optimization_with_params(symbol, fallback_res, candles_by_res, best_gens, best_pop_size, best_elites, best_mut_rate, best_tourn, best_scale, best_cross, best_weight)
                if success:
                    print(BOLD + GREEN + f"[OOS Failure Fallback] Strategy optimization succeeded on fallback resolution {fallback_res}!" + RESET)
                    break
    
    return success
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
    
    # Check wallet balance to adapt target assets
    active_idx = None
    if os.getenv("DELTA_API_KEY_3"):
        active_idx = 3
    elif os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY"):
        active_idx = 1
    
    wallet_balance = 0.0
    if active_idx:
        wallet_balance = get_live_usdt_balance(account_idx=active_idx)
    
    print(f"\n{CYAN}[Auto-Pilot] Checking Wallet Balance... USDT Available: ${wallet_balance:.2f}{RESET}")
    
    target_symbols = []
    
    # 1. Dynamically scan Delta Exchange for crypto perp assets that fit within leverage/balance constraints
    try:
        print(f"{CYAN}[Auto-Pilot] Scanning Delta Exchange for optimal high-volume crypto assets...{RESET}")
        url = "https://api.india.delta.exchange/v2/tickers"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                tickers = json.loads(response.read().decode('utf-8')).get('result', [])
                tradable = []
                # If balance is zero or unconfigured, default to $50 to scan standard assets
                eff_balance = wallet_balance if wallet_balance > 0 else 50.0
                
                for t in tickers:
                    if t.get('contract_type') != 'perpetual_futures' or t.get('top_tag') != 'crypto':
                        continue
                    try:
                        val = float(t.get('contract_value', 1.0))
                        price = float(t.get('mark_price') or t.get('close') or 0)
                        notional = val * price
                        if price <= 0:
                            continue
                        
                        # Ensure the minimum order size (1 contract notional value) does not exceed 20x the effective balance.
                        # This protects small accounts from instant liquidation due to high mandatory leverage.
                        if notional <= eff_balance * 20:
                            tradable.append({
                                'symbol': t['symbol'],
                                'notional': notional,
                                'turnover_usd': float(t.get('turnover_usd') or 0)
                            })
                    except Exception:
                        continue
                
                tradable.sort(key=lambda x: x['turnover_usd'], reverse=True)
                target_symbols = [x['symbol'] for x in tradable[:3]]
                
                if wallet_balance > 0 and wallet_balance <= 5.0:
                    print(f"{YELLOW}[Auto-Pilot] Low balance detected (${wallet_balance:.2f}). Dynamically restricted search to micro-contract assets with notional values under ${wallet_balance * 20:.2f}.{RESET}")
                else:
                    print(f"{GREEN}[Auto-Pilot] Balance check passed. Selecting highest volume tradable crypto assets.{RESET}")
    except Exception as e:
        print(f"{RED}[Auto-Pilot] Dynamic scanning failed: {e}. Falling back to preconfigured assets.{RESET}")
        
    if not target_symbols:
        # Fallback to preconfigured cryptos (SOLUSD, XRPUSD)
        for k, v in PRECONFIGURED_ASSETS.items():
            if v['category'] == 'Cryptocurrency':
                target_symbols.append(v['symbol'])
            
    print(f"\n{CYAN}[Auto-Pilot] Step 1: Target Assets Identified: {', '.join(target_symbols)}{RESET}")
    time.sleep(2)
    
    # 2. Iterate and optimize via Meta-GA autonomously
    valid_symbols = []
    for sym in target_symbols:
        print(f"\n{CYAN}[Auto-Pilot] Step 2: Optimizing Strategy via Meta-GA for {sym} on {resolution}...{RESET}")
        success = run_meta_genetic_optimization(sym, resolution, meta_generations=5, meta_pop_size=10)
        if success:
            valid_symbols.append(sym)
        else:
            print(f"{RED}[Auto-Pilot] Skipping {sym} due to OOS optimization failure.{RESET}")
        time.sleep(1)
        
    target_symbols = valid_symbols
    if not target_symbols:
        print(f"\n{RED}[Auto-Pilot] All target assets failed optimization. Aborting Auto-Pilot.{RESET}")
        return
        
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
                
    acc_idx_str = str(account_idx)
    env_dict[f"DELTA_API_KEY_{acc_idx_str}"] = key
    env_dict[f"DELTA_API_SECRET_{acc_idx_str}"] = secret
    if name:
        env_dict[f"DELTA_ACCOUNT_NAME_{acc_idx_str}"] = name
    else:
        if acc_idx_str == '1':
            env_dict[f"DELTA_ACCOUNT_NAME_{acc_idx_str}"] = "LONG_Account"
        elif acc_idx_str == '2':
            env_dict[f"DELTA_ACCOUNT_NAME_{acc_idx_str}"] = "SHORT_Account"
        else:
            env_dict[f"DELTA_ACCOUNT_NAME_{acc_idx_str}"] = "BOTH_Account"
        
    if acc_idx_str == '1':
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
                
    acc_idx_str = str(account_idx)
    env_dict.pop(f"DELTA_API_KEY_{acc_idx_str}", None)
    env_dict.pop(f"DELTA_API_SECRET_{acc_idx_str}", None)
    env_dict.pop(f"DELTA_ACCOUNT_NAME_{acc_idx_str}", None)
    
    if acc_idx_str == '1':
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
    acc_idx_str = str(account_idx)
    if acc_idx_str == '3':
        api_key = os.getenv("DELTA_API_KEY_3")
        api_secret = os.getenv("DELTA_API_SECRET_3")
    elif acc_idx_str == '2':
        api_key = os.getenv("DELTA_API_KEY_2")
        api_secret = os.getenv("DELTA_API_SECRET_2")
    else:
        api_key = os.getenv("DELTA_API_KEY_1") or os.getenv("DELTA_API_KEY")
        api_secret = os.getenv("DELTA_API_SECRET_1") or os.getenv("DELTA_API_SECRET")
    
    if not api_key or not api_secret:
        return None, f"API credentials for Account {acc_idx_str} not configured."
        
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
                    err_val = data.get('error', {})
                    if isinstance(err_val, dict):
                        err_msg = err_val.get('message', 'Unknown error')
                    else:
                        err_msg = str(err_val)
                    return None, f"API Error: {err_msg}"
            else:
                return None, f"HTTP Error {response.status}"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            reset_ms = e.headers.get('X-RATE-LIMIT-RESET')
            if reset_ms:
                try:
                    reset_sec = float(reset_ms) / 1000.0
                except (TypeError, ValueError):
                    reset_sec = 5.0
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
            err_val = err_data.get('error', {})
            if isinstance(err_val, dict):
                err_msg = err_val.get('message') or err_val.get('code') or e.reason
            else:
                err_msg = str(err_val) or e.reason
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
        positions, err = make_authenticated_request("GET", "/v2/positions/margined", account_idx=idx)
        if err:
            print(f"  {RED}Error fetching positions: {err}{RESET}\n")
        else:
            active_positions = [pos for pos in positions if int(float(pos.get('size', 0))) != 0] if positions else []
            if not active_positions:
                print("  No active open positions.\n")
            else:
                pos_header = f" {'Symbol':<12} │ {'Direction':<10} │ {'Size':<10} │ {'Entry Price':<14} │ {'Realized P&L':<14}"
                print(BOLD + pos_header + RESET)
                print("─" * (len(pos_header) + 1))
                for pos in active_positions:
                    size = int(float(pos.get('size', 0)))
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
CONTRACT_VALUE_CACHE = {
    'BTCUSD': 0.0001,
    'ETHUSD': 0.001,
    'SOLUSD': 0.01,
    'AVAXUSD': 0.1,
    'BNBUSD': 0.01,
    'XAUTUSD': 0.01
}

def get_contract_value(symbol):
    """
    Fetches the contract value (asset multiplier) of the symbol from Delta Exchange.
    Uses memory cache first to prevent latency/rate-limit leaks.
    """
    if symbol in CONTRACT_VALUE_CACHE:
        return CONTRACT_VALUE_CACHE[symbol]
        
    try:
        url = "https://api.india.delta.exchange/v2/tickers"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                tickers = json.loads(response.read().decode('utf-8')).get('result', [])
                for t in tickers:
                    sym = t.get('symbol')
                    val = t.get('contract_value')
                    if sym and val is not None:
                        CONTRACT_VALUE_CACHE[sym] = float(val)
                if symbol in CONTRACT_VALUE_CACHE:
                    return CONTRACT_VALUE_CACHE[symbol]
    except Exception:
        pass
    return 1.0

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
    positions, err = make_authenticated_request("GET", "/v2/positions/margined", account_idx=account_idx)
    if err or not positions:
        return None, f"No positions fetched or error: {err}"
        
    for pos in positions:
        if pos.get('product_symbol') == symbol:
            size = int(float(pos.get('size', 0)))
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

def parse_resolution_input(user_input, default_val='1d', is_menu_choice=False):
    """
    Cleans and parses resolution input. Strips quotes and allows both
    digit choices (e.g. '5') and direct codes (e.g. '1h').
    """
    cleaned = user_input.replace("'", "").replace('"', '').strip().lower()
    sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
    
    for res in sorted_resolutions:
        if cleaned == res.lower():
            return res
            
    if is_menu_choice and cleaned.isdigit():
        idx = int(cleaned) - 1
        if 0 <= idx < len(sorted_resolutions):
            return sorted_resolutions[idx]
            
    # Protect against PowerShell evaluating 1d as decimal 1
    if not is_menu_choice and cleaned == '1':
        return '1d'
            
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
    Fetches candle data from the Delta Exchange API using pagination to avoid HTTP 400 Bad Request.
    Uses 500-candle chunks, moving backwards in time.
    """
    chunk_size = 500
    all_candles = []
    end_time = int(time.time())
    last_err = "No data"
    
    while len(all_candles) < candle_count:
        needed = min(chunk_size, candle_count - len(all_candles))
        # Buffer of 3x to handle weekends for traditional assets
        seconds_needed = int(needed * 3.0 * resolution_to_seconds(resolution))
        start_time = end_time - seconds_needed

        params = {
            'symbol': symbol,
            'resolution': resolution,
            'start': start_time,
            'end': end_time
        }
        query = urllib.parse.urlencode(params)
        
        urls_to_try = [
            f"https://api.india.delta.exchange/v2/history/candles?{query}",
            f"https://api.delta.exchange/v2/history/candles?{query}"
        ]
        
        chunk = []
        for url in urls_to_try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode('utf-8'))
                        if data.get('success'):
                            chunk = data.get('result', [])
                            if chunk:
                                break
                        else:
                            last_err = f"API success=false: {data.get('error', {}).get('message', 'Unknown error')}"
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    reset_ms = e.headers.get('X-RATE-LIMIT-RESET', '5000')
                    try:
                        reset_sec = float(reset_ms) / 1000.0
                    except:
                        reset_sec = 5.0
                    sleep_dur = min(300.0, reset_sec)
                    print(f"\n{YELLOW}[Rate Limit] Auto-sleeping for {sleep_dur:.2f}s...{RESET}")
                    time.sleep(sleep_dur)
                    break # Break inner loop to retry this chunk on next while iteration
                else:
                    last_err = f"HTTP error {e.code}"
            except Exception as e:
                last_err = f"Error: {str(e)}"
                
        if not chunk:
            if all_candles:
                break
            return [], last_err
            
        chunk.sort(key=lambda x: x['time'])
        all_candles = chunk + all_candles
        
        # Deduplicate
        unique_candles = []
        seen_times = set()
        for c in all_candles:
            if c['time'] not in seen_times:
                seen_times.add(c['time'])
                unique_candles.append(c)
        all_candles = unique_candles
        
        # Advance end_time
        end_time = min(chunk, key=lambda x: x['time'])['time'] - 1
        
        # If we barely got any data despite 3x buffer, we might have hit history start
        if len(chunk) < int(needed * 0.2):
            break

    all_candles.sort(key=lambda x: x['time'])
    return all_candles[-candle_count:], None

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
    """Fetches the available balance (USDT/USD/INR) for the specified account."""
    balances, err = make_authenticated_request("GET", "/v2/wallet/balances", account_idx=account_idx)
    if err or not balances:
        return 0.0
    preferred = ['USDT', 'USD', 'INR']
    for asset in preferred:
        for bal in balances:
            if bal.get('asset_symbol') == asset:
                val = float(bal.get('balance', 0.0))
                if val > 0:
                    return val
    # fallback: return any non-zero balance
    for bal in balances:
        val = float(bal.get('balance', 0.0))
        if val > 0:
            return val
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
        # Load ensemble config
        ensemble = []
        if symbol in opt_settings and "ensemble" in opt_settings[symbol]:
            ensemble = opt_settings[symbol]["ensemble"]
        else:
            fast = opt_settings.get(f"{symbol}_{resolution}", {}).get("fast_period", 9)
            slow = opt_settings.get(f"{symbol}_{resolution}", {}).get("slow_period", 21)
            macro = opt_settings.get(f"{symbol}_{resolution}", {}).get("macro_multiplier", 4)
            session = opt_settings.get(f"{symbol}_{resolution}", {}).get("session_name", '24_7')
            ensemble = [{
                "resolution": resolution,
                "fast_period": fast,
                "slow_period": slow,
                "session_name": session,
                "macro_multiplier": macro
            }]
            
        print(f"  {symbol}: Using {len(ensemble)}-config Multi-EMA Ensemble.")
        
        # Initialize tracking states
        last_evaluated_candle_time[symbol] = {}
        config_signals = []
        atr_sum = 0
        valid_atrs = 0
        
        # Fetch candles for each unique resolution
        unique_res = list(set([cfg["resolution"] for cfg in ensemble]))
        candles_by_res = {}
        for r in unique_res:
            req_candles = 200
            c_data, err = fetch_candle_data(symbol, r, req_candles)
            if not err and c_data and len(c_data) >= 2:
                candles_by_res[r] = c_data
                last_evaluated_candle_time[symbol][r] = c_data[-2]['time']
            time.sleep(0.5)
            
        # Calculate initial signal for each configuration
        for cfg in ensemble:
            r = cfg["resolution"]
            if r not in candles_by_res:
                continue
            closes = [c['close'] for c in candles_by_res[r]]
            fast_ema = calculate_ema(closes, cfg["fast_period"])
            slow_ema = calculate_ema(closes, cfg["slow_period"])
            
            if cfg["macro_multiplier"] > 0:
                macro_ema = calculate_ema(closes, cfg["slow_period"] * cfg["macro_multiplier"])
            else:
                macro_ema = [None] * len(closes)
                
            atr_vals = calculate_atr(candles_by_res[r], 14)
            if atr_vals and atr_vals[-1] is not None:
                atr_sum += atr_vals[-1]
                valid_atrs += 1
                
            if len(fast_ema) >= 2 and fast_ema[-2] is not None and slow_ema[-2] is not None:
                f_closed = fast_ema[-2]
                s_closed = slow_ema[-2]
                m_closed = macro_ema[-2]
                cl_closed = closes[-2]
                
                # Session check
                is_valid_time = True
                sess = cfg["session_name"]
                if sess != '24_7':
                    curr_min = (int(candles_by_res[r][-2]['time']) // 60) % 1440
                    if sess == 'US':
                        is_valid_time = 810 <= curr_min <= 1200
                    elif sess == 'EU':
                        is_valid_time = 420 <= curr_min <= 930
                    elif sess == 'ASIA':
                        is_valid_time = 0 <= curr_min <= 510
                        
                if is_valid_time:
                    if f_closed > s_closed and (m_closed is None or cl_closed > m_closed):
                        config_signals.append(1)
                    elif f_closed < s_closed and (m_closed is None or cl_closed < m_closed):
                        config_signals.append(-1)
                    else:
                        config_signals.append(0)
                else:
                    config_signals.append(0)
                    
        # Consensus state calculation
        if config_signals:
            total_signal = sum(config_signals)
            threshold = max(1, len(ensemble) - 1)
            if total_signal >= threshold:
                curr_state = "LONG"
            elif total_signal <= -threshold:
                curr_state = "SHORT"
            else:
                curr_state = "FLAT"
        else:
            curr_state = "FLAT"
            
        states[symbol] = curr_state
        trade_details[symbol] = {'entry_price': 0, 'avg_price': 0, 'pyramid_count': 0, 'highest': 0, 'lowest': float('inf'), 'stop_loss': 0}
        avg_atr_val = atr_sum / valid_atrs if valid_atrs > 0 else 0.0
        print(f"  {symbol}: Tracked. Initial Consensus: {GREEN if curr_state=='LONG' else (RED if curr_state=='SHORT' else YELLOW)}{curr_state}{RESET} (Avg ATR: {avg_atr_val:.4f})")
        
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
            table_header = f" {'Symbol':<10} │ {'Price':<12} │ {'Fast':<10} │ {'Slow':<10} │ {'Res':<10} │ {'ATR':<10} │ {'State':<12}"
            print(BOLD + table_header + RESET)
            print("─" * (len(table_header) + 1))
            
            for symbol in symbols:
                # Load ensemble config
                ensemble = []
                if symbol in opt_settings and "ensemble" in opt_settings[symbol]:
                    ensemble = opt_settings[symbol]["ensemble"]
                else:
                    fast = opt_settings.get(f"{symbol}_{resolution}", {}).get("fast_period", 9)
                    slow = opt_settings.get(f"{symbol}_{resolution}", {}).get("slow_period", 21)
                    macro = opt_settings.get(f"{symbol}_{resolution}", {}).get("macro_multiplier", 4)
                    session = opt_settings.get(f"{symbol}_{resolution}", {}).get("session_name", '24_7')
                    ensemble = [{
                        "resolution": resolution,
                        "fast_period": fast,
                        "slow_period": slow,
                        "session_name": session,
                        "macro_multiplier": macro
                    }]
                    
                # Fetch candles for unique resolutions
                unique_res = list(set([cfg["resolution"] for cfg in ensemble]))
                candles_by_res = {}
                fetch_failed = False
                for r in unique_res:
                    req_candles = 200
                    c_data, err = fetch_candle_data(symbol, r, req_candles)
                    if not err and c_data and len(c_data) >= 2:
                        candles_by_res[r] = c_data
                    else:
                        fetch_failed = True
                    time.sleep(0.3)
                    
                if fetch_failed or not candles_by_res:
                    print(f" {symbol:<10} │ {RED}{'ERR_FETCH':<12}{RESET} │ {'-':<10} │ {'-':<10} │ {'-':<10} │ {'-':<10} │ {RED}{'ERROR':<12}{RESET}")
                    states[symbol] = "ERROR"
                    continue
                    
                # Calculate average ATR & latest close (from first config/resolution)
                base_res = ensemble[0]["resolution"]
                latest_close = candles_by_res[base_res][-1]['close']
                atr_sum = 0
                valid_atrs = 0
                for r in unique_res:
                    if r in candles_by_res:
                        atr_vals = calculate_atr(candles_by_res[r], 14)
                        if atr_vals and atr_vals[-1] is not None:
                            atr_sum += atr_vals[-1]
                            valid_atrs += 1
                curr_atr = atr_sum / valid_atrs if valid_atrs > 0 else 0.0
                
                # Check for new closed candles in any resolution to trigger crossover check
                has_new_candle = False
                for r in unique_res:
                    closed_candle_time = candles_by_res[r][-2]['time']
                    if r not in last_evaluated_candle_time[symbol]:
                        last_evaluated_candle_time[symbol][r] = closed_candle_time
                        has_new_candle = True
                    elif closed_candle_time > last_evaluated_candle_time[symbol][r]:
                        last_evaluated_candle_time[symbol][r] = closed_candle_time
                        has_new_candle = True
                        
                f_disp = f"{ensemble[0]['fast_period']}"
                s_disp = f"{ensemble[0]['slow_period']}"
                m_disp = f"{ensemble[0]['resolution']}"
                pos_color = GREEN if states[symbol] == "LONG" else (RED if states[symbol] == "SHORT" else YELLOW)
                print(f" {symbol:<10} │ {latest_close:<12.4f} │ {f_disp:<10} │ {s_disp:<10} │ {m_disp:<10} │ {curr_atr:<10.4f} │ {pos_color}{states[symbol]:<12}{RESET}")
                
                # Perform consensus evaluation if a new candle closed
                if has_new_candle:
                    config_signals = []
                    cl_closed_val = None
                    for cfg in ensemble:
                        r = cfg["resolution"]
                        if r not in candles_by_res:
                            continue
                        closes = [c['close'] for c in candles_by_res[r]]
                        fast_ema = calculate_ema(closes, cfg["fast_period"])
                        slow_ema = calculate_ema(closes, cfg["slow_period"])
                        if cfg["macro_multiplier"] > 0:
                            macro_ema = calculate_ema(closes, cfg["slow_period"] * cfg["macro_multiplier"])
                        else:
                            macro_ema = [None] * len(closes)
                            
                        if len(fast_ema) >= 2 and fast_ema[-2] is not None and slow_ema[-2] is not None:
                            f_closed = fast_ema[-2]
                            s_closed = slow_ema[-2]
                            m_closed = macro_ema[-2]
                            cl_closed = closes[-2]
                            if cl_closed_val is None:
                                cl_closed_val = cl_closed
                                
                            is_valid_time = True
                            sess = cfg["session_name"]
                            if sess != '24_7':
                                curr_min = (int(candles_by_res[r][-2]['time']) // 60) % 1440
                                if sess == 'US':
                                    is_valid_time = 810 <= curr_min <= 1200
                                elif sess == 'EU':
                                    is_valid_time = 420 <= curr_min <= 930
                                elif sess == 'ASIA':
                                    is_valid_time = 0 <= curr_min <= 510
                                    
                            if is_valid_time:
                                if f_closed > s_closed and (m_closed is None or cl_closed > m_closed):
                                    config_signals.append(1)
                                elif f_closed < s_closed and (m_closed is None or cl_closed < m_closed):
                                    config_signals.append(-1)
                                else:
                                    config_signals.append(0)
                            else:
                                config_signals.append(0)
                                
                    if config_signals:
                        total_signal = sum(config_signals)
                        threshold = max(1, len(ensemble) - 1)
                        if total_signal >= threshold:
                            new_state = "LONG"
                        elif total_signal <= -threshold:
                            new_state = "SHORT"
                        else:
                            new_state = "FLAT"
                    else:
                        new_state = "FLAT"
                        
                    # Handle state transition
                    if new_state != states[symbol]:
                        print("\a", end="")
                        alert_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        cl_disp_price = cl_closed_val if cl_closed_val is not None else latest_close
                        alerts.append(f"[{alert_time}] ★ {symbol} consensus crossed over to {new_state} at {cl_disp_price:.4f} USD")
                        states[symbol] = new_state
                        td = trade_details.setdefault(symbol, {'entry_price': 0, 'avg_price': 0, 'pyramid_count': 0, 'highest': 0, 'lowest': float('inf'), 'stop_loss': 0})
                        
                        if trade:
                            if new_state == "LONG":
                                print(f"\n{GREEN}[Trade Action] LONG consensus crossover triggered for {symbol}.{RESET}")
                                td['entry_price'] = cl_disp_price
                                td['avg_price'] = cl_disp_price
                                td['highest'] = cl_disp_price
                                td['stop_loss'] = cl_disp_price - (curr_atr * 2)
                                td['pyramid_count'] = 0
                                
                                close_res, close_err = close_position_if_any(symbol, account_idx=short_acc)
                                if close_err:
                                    print(f"  {RED}[ERROR] Close short position failed: {close_err}{RESET}")
                                    
                                # Fractional Kelly Sizing with Contract Value mapping
                                balance = get_live_usdt_balance(account_idx=long_acc)
                                sl_distance = curr_atr * 2
                                contract_val = get_contract_value(symbol)
                                dynamic_size = trade_size
                                actual_size = max(1, int(dynamic_size))
                                if balance > 0 and sl_distance > 0:
                                    dynamic_size = (balance * 0.02) / (sl_distance * contract_val)
                                    print(f"  {CYAN}Calculated Kelly Lot Size: {dynamic_size:.3f} (Bal: ${balance:.2f}, Risk: 2%, SL: ${sl_distance:.2f}, Mult: {contract_val}){RESET}")
                                    actual_size = max(1, int(dynamic_size))
                                    pct_risk = (actual_size * sl_distance * contract_val) / balance
                                    if pct_risk > 0.05:
                                        print(f"  {RED}[WARNING: Over-Leveraged] Risks {pct_risk*100.0:.1f}% of equity!{RESET}")
                                        
                                order_res, order_err = place_market_order(symbol, "buy", size=actual_size, account_idx=long_acc)
                                if order_err:
                                    print(f"  {RED}[ERROR] Order placement failed: {order_err}{RESET}")
                                else:
                                    print(f"  {GREEN}[SUCCESS] LONG order placed successfully.{RESET}")
                                    
                            elif new_state == "SHORT":
                                print(f"\n{RED}[Trade Action] SHORT consensus crossover triggered for {symbol}.{RESET}")
                                td['entry_price'] = cl_disp_price
                                td['avg_price'] = cl_disp_price
                                td['lowest'] = cl_disp_price
                                td['stop_loss'] = cl_disp_price + (curr_atr * 2)
                                td['pyramid_count'] = 0
                                
                                close_res, close_err = close_position_if_any(symbol, account_idx=long_acc)
                                if close_err:
                                    print(f"  {RED}[ERROR] Close long position failed: {close_err}{RESET}")
                                    
                                # Fractional Kelly Sizing with Contract Value mapping
                                balance = get_live_usdt_balance(account_idx=short_acc)
                                sl_distance = curr_atr * 2
                                contract_val = get_contract_value(symbol)
                                dynamic_size = trade_size
                                actual_size = max(1, int(dynamic_size))
                                if balance > 0 and sl_distance > 0:
                                    dynamic_size = (balance * 0.02) / (sl_distance * contract_val)
                                    print(f"  {CYAN}Calculated Kelly Lot Size: {dynamic_size:.3f} (Bal: ${balance:.2f}, Risk: 2%, SL: ${sl_distance:.2f}, Mult: {contract_val}){RESET}")
                                    actual_size = max(1, int(dynamic_size))
                                    pct_risk = (actual_size * sl_distance * contract_val) / balance
                                    if pct_risk > 0.05:
                                        print(f"  {RED}[WARNING: Over-Leveraged] Risks {pct_risk*100.0:.1f}% of equity!{RESET}")
                                        
                                order_res, order_err = place_market_order(symbol, "sell", size=actual_size, account_idx=short_acc)
                                if order_err:
                                    print(f"  {RED}[ERROR] Order placement failed: {order_err}{RESET}")
                                else:
                                    print(f"  {GREEN}[SUCCESS] SHORT order placed successfully.{RESET}")
                                    
                            elif new_state == "FLAT":
                                print(f"\n{YELLOW}[Trade Action] FLAT consensus crossover triggered for {symbol}. Closing all positions.{RESET}")
                                close_position_if_any(symbol, account_idx=long_acc)
                                close_position_if_any(symbol, account_idx=short_acc)
                                td['entry_price'] = 0
                
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
                            contract_val = get_contract_value(symbol)
                            dynamic_size = trade_size
                            if balance > 0 and sl_distance > 0:
                                dynamic_size = (balance * 0.01) / (sl_distance * contract_val) # Half-Kelly for Pyramids
                            actual_size = max(1, int(dynamic_size))
                            order_res, order_err = place_market_order(symbol, "buy", size=actual_size, account_idx=long_acc)
                            if order_err:
                                print(f"  {RED}[ERROR] Pyramid order failed: {order_err}{RESET}")
                        td['avg_price'] = (td['avg_price'] + latest_close) / 2
                        td['pyramid_count'] += 1

                elif states[symbol] == "SHORT":
                    if td['lowest'] == float('inf') or latest_close < td['lowest']:
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
                            contract_val = get_contract_value(symbol)
                            dynamic_size = trade_size
                            if balance > 0 and sl_distance > 0:
                                dynamic_size = (balance * 0.01) / (sl_distance * contract_val) # Half-Kelly for Pyramids
                            actual_size = max(1, int(dynamic_size))
                            order_res, order_err = place_market_order(symbol, "sell", size=actual_size, account_idx=short_acc)
                            if order_err:
                                print(f"  {RED}[ERROR] Pyramid order failed: {order_err}{RESET}")
                        td['avg_price'] = (td['avg_price'] + latest_close) / 2
                        td['pyramid_count'] += 1
                # ------------------------------------------------------
                
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

def select_symbols_interactive():
    """
    Interactively select symbols via menu supporting single, multi-select, and custom comma-separated entries.
    Returns (symbols, label) or (None, None) if cancelled/invalid.
    """
    clear_screen()
    print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
    print(BOLD + CYAN + "│" + f" SELECT ASSETS TO MONITOR ".center(50) + "│" + RESET)
    print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
    print(BOLD + CYAN + "│" + f"  1. Monitor All Preconfigured Assets".ljust(48) + "│" + RESET)
    print(BOLD + CYAN + "│" + f"  2. Select / Multi-Select Preconfigured Assets".ljust(48) + "│" + RESET)
    print(BOLD + CYAN + "│" + f"  3. Enter Custom Symbol(s) (Comma-separated)".ljust(48) + "│" + RESET)
    print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
    
    choice = input(BOLD + "\nSelect choice (1-3, Default 1): " + RESET).strip()
    if not choice:
        choice = '1'
        
    if choice == '1':
        return [PRECONFIGURED_ASSETS[k]['symbol'] for k in sorted(PRECONFIGURED_ASSETS.keys(), key=int)], "ALL"
    elif choice == '2':
        clear_screen()
        print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
        print(BOLD + CYAN + "│" + f" MULTI-SELECT PRECONFIGURED ASSETS ".center(50) + "│" + RESET)
        print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
        for k, v in sorted(PRECONFIGURED_ASSETS.items(), key=lambda x: int(x[0])):
            line = f"  {k}. {v['name']}"
            print(BOLD + CYAN + "│" + f"{line:<48}" + "│" + RESET)
        print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
        print(f"\n{YELLOW}[Help: Enter numbers separated by commas (e.g. 1,3,5) or range (e.g. 1-4)]{RESET}")
        selection = input(BOLD + "Select assets: " + RESET).strip()
        if not selection:
            return None, None
            
        selected_keys = set()
        parts = selection.split(',')
        for part in parts:
            part = part.strip()
            if '-' in part:
                try:
                    start, end = part.split('-')
                    for num in range(int(start), int(end) + 1):
                        if str(num) in PRECONFIGURED_ASSETS:
                            selected_keys.add(str(num))
                except ValueError:
                    pass
            elif part in PRECONFIGURED_ASSETS:
                selected_keys.add(part)
                
        if not selected_keys:
            print(f"{RED}No valid assets selected.{RESET}")
            time.sleep(1.5)
            return None, None
            
        symbols = [PRECONFIGURED_ASSETS[k]['symbol'] for k in sorted(list(selected_keys), key=int)]
        label = ",".join(symbols) if len(symbols) < 4 else f"{len(symbols)}_ASSETS"
        return symbols, label
        
    elif choice == '3':
        print(f"\n{YELLOW}Popular symbols on Delta Exchange:{RESET}")
        print(f"  {CYAN}Cryptocurrencies:{RESET} BTCUSD, ETHUSD, SOLUSD, XRPUSD, BNBUSD, AVAXUSD, SUIUSD, DOGEUSD, PEPEUSD")
        print(f"  {CYAN}Stock Indices:{RESET}    SPYXUSD, QQQXUSD")
        print(f"  {CYAN}Commodities:{RESET}      XAUTUSD, SLVONUSD\n")
        sym_input = input(BOLD + "Enter symbol(s) (e.g. BTCUSD, ETHUSD): " + RESET).strip().upper()
        if not sym_input:
            print("Invalid input.")
            time.sleep(1.5)
            return None, None
            
        symbols = [s.strip() for s in sym_input.split(',') if s.strip()]
        if not symbols:
            print("Invalid input.")
            time.sleep(1.5)
            return None, None
            
        label = ",".join(symbols) if len(symbols) < 4 else f"{len(symbols)}_ASSETS"
        return symbols, label
        
    return None, None

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
                        if bal.get('asset_symbol') in ['USDT', 'USD', 'INR', 'DET']:
                            bval = float(bal.get('balance', 0))
                            if bval > 0 or not found:
                                cached_balance = f"{bval:,.2f} {bal.get('asset_symbol')}"
                                found = True
                                if bval > 0:
                                    break
                    if not found and len(balances) > 0:
                        non_zero = [b for b in balances if float(b.get('balance', 0)) > 0]
                        if non_zero:
                            cached_balance = f"{float(non_zero[0].get('balance', 0)):,.2f} {non_zero[0].get('asset_symbol')}"
                        else:
                            if balances:
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
            symbols, label = select_symbols_interactive()
            if not symbols:
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
            symbols_to_opt, label = select_symbols_interactive()
            if not symbols_to_opt:
                continue
                
            print(BOLD + CYAN + "┌" + "─"*50 + "┐" + RESET)
            print(BOLD + CYAN + "│" + f" SELECT OPTIMIZATION TIMEFRAME ".center(50) + "│" + RESET)
            print(BOLD + CYAN + "├" + "─"*50 + "┤" + RESET)
            sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
            for idx, res in enumerate(sorted_resolutions, 1):
                line = f"  {idx}. {res} ({SUPPORTED_RESOLUTIONS[res]})"
                print(BOLD + CYAN + "│" + f"{line:<48}" + "│" + RESET)
            print(BOLD + CYAN + "└" + "─"*50 + "┘" + RESET)
            
            print(f"\n{YELLOW}[Help: Select the timeframe/candle size(s). Comma-separated lists are allowed (e.g. '1h,4h' or '5,6').]{RESET}")
            res_choice = input(BOLD + "Select resolution(s) (1-8, Default 1d): " + RESET).strip()
            res_choices = [r.strip() for r in res_choice.split(',') if r.strip()]
            resolutions_to_opt = []
            if not res_choices:
                resolutions_to_opt = ['1d']
            else:
                for rc in res_choices:
                    resolutions_to_opt.append(parse_resolution_input(rc, '1d', is_menu_choice=True))
                    
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
                for s_opt in symbols_to_opt:
                    for r_opt in resolutions_to_opt:
                        print(BOLD + GREEN + f"\n>>> Starting Meta-GA Hyperparameter Tuning for {s_opt} ({r_opt}) <<<" + RESET)
                        run_meta_genetic_optimization(s_opt, r_opt, meta_gens, meta_pop)
            else:
                generations = get_validated_int_input(
                    "Enter number of GA generations (Default 15): ",
                    "Evolution cycles for finding best EMAs. Recommended 15, Max 50.",
                    15, 1, 50
                )
                for s_opt in symbols_to_opt:
                    for r_opt in resolutions_to_opt:
                        print(BOLD + GREEN + f"\n>>> Starting Strategy Optimization for {s_opt} ({r_opt}) <<<" + RESET)
                        run_genetic_optimization(s_opt, r_opt, generations)
                
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
                    symbols, label = select_symbols_interactive()
                    if not symbols:
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
                    resolution = parse_resolution_input(res_choice, '1m', is_menu_choice=True)
                            
                    poll_interval = get_validated_int_input(
                        "Enter polling interval in seconds (5-300, Default 15): ",
                        "How often the bot checks for new candles and calculates crossovers. Min 5s, Max 300s.",
                        15, 5, 300
                    )
                        
                    daemon_args = []
                    if label == "ALL":
                        daemon_args += ["--symbol", "ALL"]
                    else:
                        daemon_args += ["--symbol", ",".join(symbols)]
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
            clear_screen()
            print(BOLD + MAGENTA + "┌" + "─"*50 + "┐" + RESET)
            print(BOLD + MAGENTA + "│" + " SELECT AUTOPILOT RESOLUTION ".center(50) + "│" + RESET)
            print(BOLD + MAGENTA + "├" + "─"*50 + "┤" + RESET)
            sorted_resolutions = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']
            for idx, res in enumerate(sorted_resolutions, 1):
                line = f"  {idx}. {res} ({SUPPORTED_RESOLUTIONS[res]})"
                print(BOLD + MAGENTA + "│" + f"{line:<48}" + "│" + RESET)
            print(BOLD + MAGENTA + "└" + "─"*50 + "┘" + RESET)
            
            res_choice = input(BOLD + "\nSelect autopilot base resolution (1-8, Default 1h): " + RESET).strip()
            resolution = parse_resolution_input(res_choice, '1h', is_menu_choice=True)
            
            run_autopilot_setup(resolution, 10)
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
        resolution = parse_resolution_input(res_choice, '1d', is_menu_choice=True)

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
    parser.add_argument('-r', '--resolution', type=str, default='1d', help='Candle resolution timeframe(s), comma-separated (default: 1d)')
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
        sys.exit(0)

    # 2. Strategy Optimization
    if args.optimize or args.meta_optimize:
        if not args.symbol:
            print(f"{RED}Error: You must specify a symbol (e.g. -s SOLUSD or -s SOLUSD,XRPUSD or -s ALL) to run optimization.{RESET}")
            sys.exit(1)
        
        raw_symbol = args.symbol.upper()
        symbols_to_opt = []
        
        if raw_symbol == 'ALL':
            symbols_to_opt = [v['symbol'] for k, v in sorted(PRECONFIGURED_ASSETS.items(), key=lambda x: int(x[0]))]
        else:
            symbols_to_opt = [s.strip() for s in raw_symbol.split(',') if s.strip()]
            
        raw_res = args.resolution
        resolutions_to_opt = [parse_resolution_input(r.strip(), '1d') for r in raw_res.split(',') if r.strip()]
        
        for sym in symbols_to_opt:
            for res in resolutions_to_opt:
                print(BOLD + GREEN + f"\n>>> Starting Strategy Optimization Process for {sym} ({res}) <<<" + RESET)
                if args.meta_optimize:
                    run_meta_genetic_optimization(sym, res, args.meta_generations, args.meta_pop_size)
                else:
                    run_genetic_optimization(sym, res, args.opt_generations)
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
