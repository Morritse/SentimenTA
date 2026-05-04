import os
import time
import pytz
from datetime import datetime
from dotenv import load_dotenv
from alpaca.trading.enums import OrderSide
from social_scanner import SocialScanner
from technical_analysis import TechnicalAnalyzer
from position_manager import PositionManager
import pandas as pd

class Trader:
    def __init__(self):
        self.position_manager = PositionManager()
    
    def is_market_open_period(self):
        """Check if we're in the first 30 minutes of market open (9:30 AM to 10:00 AM EST)"""
        now = datetime.now(pytz.timezone('US/Eastern'))
        minutes_since_midnight = now.hour * 60 + now.minute
        # Market opens at 9:30 AM (570 mins) and 30-min window ends at 10:00 AM (600 mins)
        return 570 <= minutes_since_midnight < 600
    
    def manage_existing_positions(self, analyzer):
        """Manage existing positions"""
        current_positions = self.position_manager.update_positions()
        if not current_positions:
            return
            
        # Check each position
        for symbol in list(current_positions.keys()):
            position = current_positions[symbol]
            side = OrderSide.BUY if float(position.qty) > 0 else OrderSide.SELL
            technical_data = analyzer.analyze_stock(symbol, side)
            
            if technical_data and self.should_exit_position(symbol, technical_data):
                print(f"\nSELL {symbol}: {', '.join(technical_data['exit_signals'])}")
                self.position_manager.close_position(symbol)
    
    def find_new_opportunities(self, analyzer):
        """Find and execute new trades"""
        # Update positions and orders silently
        self.position_manager.positions = self.position_manager.update_positions(show_status=False)
        self.position_manager.update_pending_orders()
        
        # Get ranked stocks
        scanner = SocialScanner()
        df = scanner.get_trending_stocks()
        if df.empty:
            return
        
        # Show top 10 rankings
        print("\nTop 10 Ranked Stocks:")
        for _, stock in df.head(10).iterrows():
            print(f"{stock['ticker']}: Rank {stock['final_rank']:.1f} (Sentiment: {stock['sentiment_rank']:.1f}, TA: {stock['ta_rank']:.0f})")
        
        # Get current positions and pending orders
        current_positions = set(self.position_manager.positions.keys())
        pending_orders = {order['symbol'] for order in self.position_manager.pending_orders}
        
        # Check positions for staleness
        top_stocks = df.head(10)
        target_symbols = set(top_stocks['ticker'])
        now = datetime.now()
        
        for symbol in current_positions:
            position = self.position_manager.positions[symbol]
            position_age = (now - position.entry_time).total_seconds() / 3600  # Hours
            
            technical_data = analyzer.analyze_stock(symbol)
            if not technical_data:
                continue
                
            # Exit conditions:
            # 1. Not in rankings AND weak technicals
            if symbol not in df['ticker'].values:  # Check all rankings, not just top 10
                if technical_data['score'] < 0.4:
                    print(f"\nSELL {symbol}: Not in rankings, weak technicals")
                    self.position_manager.close_position(symbol)
                    
            # 2. Stale position check - more conservative
            elif position_age > 24:  # At least 24h old
                # Exit if ALL conditions met:
                if (technical_data['score'] < 0.5 and  # Weaker technicals
                    abs(position.pl_pct) < 3 and    # Little movement (now in percentage)
                    symbol not in target_symbols):      # Not in top 10
                    print(f"\nSELL {symbol}: Stale position ({position_age:.1f}h old, rank {df[df['ticker'] == symbol].iloc[0]['final_rank']:.1f})")
                    self.position_manager.close_position(symbol)
        
        # Check if we're in market open period - only allow sells
        if self.is_market_open_period():
            print("\nSkipping new positions - in first 30 minutes of market open")
            return
        
        # Enter new positions only if not at max exposure
        account = self.position_manager.get_account_info()
        total_exposure = sum(p.get_exposure(account['equity']) 
                           for p in self.position_manager.positions.values())
        
        if total_exposure < self.position_manager.max_total_exposure:
            for _, stock in top_stocks.iterrows():
                ticker = stock['ticker']
                
                # Skip if we already have position or pending order
                if ticker in current_positions:
                    print(f"\nSkipping {ticker} - already in portfolio")
                    continue
                if ticker in pending_orders:
                    print(f"\nSkipping {ticker} - order already pending")
                    continue
                
                # Check technicals
                technical_data = analyzer.analyze_stock(ticker)
                if not technical_data or technical_data['score'] < 0.4:
                    continue
                
                # Calculate position size with sentiment data
                sentiment_data = {
                    'final_rank': stock['final_rank'],
                    'sentiment_rank': stock['sentiment_rank'],
                    'ta_rank': stock['ta_rank']
                }
                
                shares, allow_trade = self.position_manager.calculate_target_position(
                    ticker,
                    technical_data['price'],
                    OrderSide.BUY,
                    target_pct=0.08,
                    technical_data=technical_data,
                    sentiment_data=sentiment_data
                )
                
                if allow_trade and shares > 0:
                    try:
                        print(f"\nBUY {ticker}: Rank {stock['final_rank']:.1f} (Sentiment: {stock['sentiment_rank']:.1f}, TA: {stock['ta_rank']:.0f})")
                        self.position_manager.place_order(ticker, shares, side=OrderSide.BUY)
                    except Exception as e:
                        if "insufficient buying power" in str(e):
                            print("\nInsufficient buying power - checking for positions to rotate...")
                            
                            # Get rankings for current positions
                            position_ranks = {}
                            for pos_symbol in current_positions:
                                rank_row = df[df['ticker'] == pos_symbol]
                                if not rank_row.empty:
                                    position_ranks[pos_symbol] = rank_row.iloc[0]['final_rank']
                                else:
                                    # Not in rankings = worst possible rank
                                    position_ranks[pos_symbol] = float('inf')
                            
                            # Sort by rank (worst first)
                            sorted_positions = sorted(position_ranks.items(), key=lambda x: (-x[1], x[0]))
                            
                            # Try to sell worst ranked positions
                            for symbol, rank in sorted_positions[-3:]:  # Try worst 3
                                if rank > stock['final_rank']:  # Only if worse than target
                                    print(f"\nRotating out of {symbol} (Rank {rank:.1f}) for {ticker} (Rank {stock['final_rank']:.1f})")
                                    self.position_manager.close_position(symbol)
                        else:
                            print(f"\nError placing order: {str(e)}")
        else:
            print(f"\nSkipping new positions - at max exposure ({total_exposure:.1%})")
    
    def should_exit_position(self, symbol, technical_data):
        """Check exit signals"""
        position = self.position_manager.positions[symbol]
        signals = technical_data['signals']
        momentum = technical_data['momentum']
        score = technical_data['score']
        
        exit_signals = []
        
        # Market open protection logic
        position_age_mins = (datetime.now() - position.entry_time).total_seconds() / 60
        if position_age_mins < 30:  # 30-min protection period
            # Only exit if:
            # 1. Hard stop hit (-10% from entry)
            if position.pl_pct < -10:  # pl_pct is now in percentage form
                exit_signals.append(f"Hard stop: {position.pl_pct:.1f}% loss")
                technical_data['exit_signals'] = exit_signals
                return True
                
            # 2. Big profit + reversal (lock in gains)
            if position.pl_pct > 7.5 and position.drawdown < -5:
                exit_signals.append(f"Profit lock: {position.drawdown:.1f}% drop from high while +{position.pl_pct:.1f}% up")
                technical_data['exit_signals'] = exit_signals
                return True
                
            # Otherwise hold through volatility
            return False
        
        # 1. Protect Profits - Tighten stops as profit grows
        if position.pl_pct > 10:  # In +10% profit (now in percentage)
            if position.drawdown < -5:  # Tighter 5% trailing stop
                exit_signals.append(f"Profit protection: {position.drawdown:.1f}% drop from high while +{position.pl_pct:.1f}% up")
                technical_data['exit_signals'] = exit_signals
                return True
        elif position.drawdown < -7.5:  # Normal 7.5% trailing stop
            exit_signals.append(f"Trailing stop: {position.drawdown:.1f}% from high")
            technical_data['exit_signals'] = exit_signals
            return True
            
        # 2. Quick Momentum Shifts - Only exit if significant drop
        if momentum < -5:
            if position.pl_pct > 5:  # Need 5% profit to use quick exit (now in percentage)
                exit_signals.append(f"Momentum reversal: {momentum:.1f}% drop while +{position.pl_pct:.1f}% up")
                technical_data['exit_signals'] = exit_signals
                return True
            
        # 3. Technical Weakness - Need multiple confirmations
        tech_signals = []
        if score < 0.4:  # Weak technical score
            if any('below both MAs' in signal for signal in signals):
                tech_signals.append("Below MAs")
            if any('Strong bearish MACD' in signal for signal in signals):
                tech_signals.append("Bearish MACD")
            if momentum < -3:  # Lower threshold with weak technicals
                tech_signals.append(f"{momentum:.1f}% momentum")
                
        # Only exit on technical weakness if multiple signals
        if len(tech_signals) >= 2:
            exit_signals.extend(tech_signals)
            technical_data['exit_signals'] = exit_signals
            return True
            
        # Need multiple signals if technicals still strong
        return len(exit_signals) >= 2
    
    def monitor_positions(self, interval_seconds=300):
        """Monitor positions and trade every 5 minutes"""
        analyzer = TechnicalAnalyzer()
        
        while True:
            print(f"\n=== Trading Loop Starting at {datetime.now()} ===")
            
            # Check if market is open
            try:
                clock = self.position_manager.trading_client.get_clock()
                if not clock.is_open:
                    print(f"\nMarket is currently closed.")
                    print(f"Next open: {clock.next_open}")
                    print(f"Sleeping for {interval_seconds} seconds before checking again...")
                    time.sleep(interval_seconds)
                    continue
            except Exception as e:
                print(f"\nError checking market clock: {str(e)}")
            
            # Run full trading cycle
            self.manage_existing_positions(analyzer)
            self.find_new_opportunities(analyzer)
            
            print(f"\nSleeping for {interval_seconds} seconds...")
            time.sleep(interval_seconds)
    
    def analyze_and_trade(self):
        """Main trading loop"""
        print("\nStarting trading system...")
        
        # Show initial portfolio status
        self.position_manager.update_positions(show_status=True)
        
        # Start monitoring loop
        self.monitor_positions()

def main():
    trader = Trader()
    trader.analyze_and_trade()

if __name__ == "__main__":
    main()
