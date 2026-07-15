# Delta Exchange Auto-Pilot Monitor 🚀

A Fully Autonomous, Genetic Algorithm (GA) powered trading bot and CLI monitor built for **Delta Exchange**. It features live dashboard monitoring, EMA crossover alerting, and a 1-click Auto-Pilot manager that dynamically picks top assets, runs a machine learning solver to find the best EMA strategy for each, and spawns a background trading daemon to execute them hands-free.

## Features
- 📊 **Interactive Terminal Dashboard**: Track multiple crypto, metals, and index assets.
- 🧬 **Genetic Algorithm Optimizer**: Uses evolutionary cycles to backtest historical candle data and find the most profitable EMA pairs (fast/slow).
- 🤖 **1-Click Auto-Pilot Manager**: Identifies 24/7 crypto markets, optimizes their EMA parameters automatically, and spawns a background daemon.
- 🔄 **Background Daemon Mode**: Trade in the background using `--start`, `--stop`, and `--status` without keeping a terminal active.
- 📱 **Mobile Termux Ready**: Highly optimized for running on Android's Termux app. 

## Installation on Termux (Android Mobile)

1. Open Termux and install required packages:
   ```bash
   pkg update -y && pkg upgrade -y
   pkg install python git -y
   ```

2. Clone this repository:
   ```bash
   git clone https://github.com/kaviyarasukav/kyoq.git
   cd kyoq
   ```

3. Run the interactive monitor:
   ```bash
   python delta_monitor.py
   ```

## Usage

When you run `python delta_monitor.py`, you'll be greeted with an interactive dashboard. 
Select **Option 13** to launch the Fully Autonomous Auto-Pilot Setup. It will handle asset selection, EMA optimization, and background trading automatically!

> **Warning:** You must enter your Delta API keys via **Option 10** before automated trading can take place. Your keys are securely stored locally in `.env`.
