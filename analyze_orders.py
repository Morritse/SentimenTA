import json
from datetime import datetime, date, time, timedelta
from collections import defaultdict

def convert_to_et(timestamp):
    # Convert UTC timestamp to ET
    dt = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    et_offset = timedelta(hours=-5)  # EST is UTC-5
    return dt + et_offset

def is_late_day(dt_et):
    # Consider "late day" as after 3:30 PM ET
    late_day_start = dt_et.replace(hour=15, minute=30, second=0, microsecond=0)
    return dt_et >= late_day_start

def is_first_hour(dt_et):
    # Check if time is between 9:30 AM and 10:30 AM ET
    market_open = dt_et.replace(hour=9, minute=30, second=0, microsecond=0)
    first_hour_end = dt_et.replace(hour=10, minute=30, second=0, microsecond=0)
    return market_open <= dt_et <= first_hour_end

def analyze_orders(orders_file):
    print("Reading orders file...")
    with open(orders_file, 'r') as f:
        orders = json.load(f)
    print(f"Found {len(orders)} orders")

    # Sort orders by timestamp
    orders.sort(key=lambda x: x['created_at'])
    
    # Track positions by date
    daily_positions = defaultdict(lambda: defaultdict(lambda: {
        'shares': 0,
        'buys': [],
        'sells': []
    }))
    
    print("\nAnalyzing trading activity...")
    
    # First pass: Record all positions
    for order in orders:
        # Skip orders that aren't filled
        if order.get('status') != 'filled':
            continue
            
        # Skip orders with missing data
        if not all(order.get(field) for field in ['symbol', 'side', 'qty', 'filled_avg_price', 'created_at']):
            continue
            
        symbol = order['symbol']
        side = order['side']
        qty = int(order['qty'])
        price = float(order['filled_avg_price'])
        dt_et = convert_to_et(order['created_at'])
        trade_date = dt_et.date()
        
        if side == 'buy':
            daily_positions[trade_date][symbol]['shares'] += qty
            daily_positions[trade_date][symbol]['buys'].append({
                'time': dt_et,
                'price': price,
                'qty': qty
            })
        else:  # sell
            daily_positions[trade_date][symbol]['shares'] -= qty
            daily_positions[trade_date][symbol]['sells'].append({
                'time': dt_et,
                'price': price,
                'qty': qty
            })

    # Analyze overnight positions
    dates = sorted(daily_positions.keys())
    
    print("\nPosition Summary by Date:")
    print("========================")
    
    for date in dates:
        print(f"\n{date}:")
        for symbol, pos in daily_positions[date].items():
            if pos['buys'] or pos['sells']:
                print(f"\n  {symbol}:")
                if pos['buys']:
                    grouped_buys = {}
                    for order in pos['buys']:
                        time_str = order['time'].strftime('%I:%M %p ET')
                        key = (time_str, order['price'])
                        grouped_buys[key] = grouped_buys.get(key, 0) + order['qty']
                    for key in sorted(grouped_buys, key=lambda k: datetime.strptime(k[0], '%I:%M %p ET')):
                        print(f"    BUY  {key[0]}: {grouped_buys[key]} shares @ ${key[1]:.2f}")
                if pos['sells']:
                    grouped_sells = {}
                    for order in pos['sells']:
                        time_str = order['time'].strftime('%I:%M %p ET')
                        key = (time_str, order['price'])
                        grouped_sells[key] = grouped_sells.get(key, 0) + order['qty']
                    for key in sorted(grouped_sells, key=lambda k: datetime.strptime(k[0], '%I:%M %p ET')):
                        print(f"    SELL {key[0]}: {grouped_sells[key]} shares @ ${key[1]:.2f}")
                
                # Check for overnight position
                if pos['shares'] > 0 and any(buy['time'].hour >= 15 for buy in pos['buys']):
                    print(f"    ** OVERNIGHT POSITION: {pos['shares']} shares **")

def calculate_average_overnight_return(orders_file):
    with open(orders_file, 'r') as f:
        orders = json.load(f)
    orders.sort(key=lambda x: x['created_at'])
    trades_by_day = defaultdict(lambda: defaultdict(list))
    for order in orders:
        if order.get('status') != 'filled':
            continue
        if not all(order.get(field) for field in ['symbol', 'side', 'qty', 'filled_avg_price', 'created_at']):
            continue
        symbol = order['symbol']
        dt_et = convert_to_et(order['created_at'])
        trade_date = dt_et.date()
        trades_by_day[trade_date][symbol].append({
            'time': dt_et,
            'price': float(order['filled_avg_price']),
            'qty': int(order['qty']),
            'side': order['side']
        })
    overnight_returns = []
    sorted_days = sorted(trades_by_day.keys())
    for i in range(len(sorted_days)-1):
        day = sorted_days[i]
        next_day = sorted_days[i+1]
        for sym in trades_by_day[day]:
            # Check if there is any buy after 3:00 PM indicating an overnight purchase
            has_overnight_buy = any(trade['side'] == 'buy' and trade['time'].hour >= 15 for trade in trades_by_day[day][sym])
            if not has_overnight_buy:
                continue
            trades_day = sorted(trades_by_day[day][sym], key=lambda x: x['time'])
            last_trade = trades_day[-1]
            if sym in trades_by_day[next_day]:
                trades_next_day = sorted(trades_by_day[next_day][sym], key=lambda x: x['time'])
                first_trade_next = trades_next_day[0]
                # Overnight return calculated from last trade price of day to first trade price of next day
                overnight_return = (first_trade_next['price'] - last_trade['price']) / last_trade['price']
                overnight_returns.append(overnight_return)
    if overnight_returns:
        avg_return = sum(overnight_returns) / len(overnight_returns)
    else:
        avg_return = 0
    print(f"\nAverage Overnight Return: {avg_return*100:.2f}%")
    
def calculate_first_hour_return(orders_file):
    with open(orders_file, 'r') as f:
        orders = json.load(f)
    orders.sort(key=lambda x: x['created_at'])
    trades_by_day = defaultdict(lambda: defaultdict(list))
    for order in orders:
        if order.get('status') != 'filled':
            continue
        if not all(order.get(field) for field in ['symbol', 'side', 'qty', 'filled_avg_price', 'created_at']):
            continue
        symbol = order['symbol']
        dt_et = convert_to_et(order['created_at'])
        trade_date = dt_et.date()
        trades_by_day[trade_date][symbol].append({
            'time': dt_et,
            'price': float(order['filled_avg_price']),
            'qty': int(order['qty']),
            'side': order['side']
        })
    first_hour_returns = []
    for day in trades_by_day:
        fh_start = datetime.combine(day, time(9, 30))
        fh_end = datetime.combine(day, time(10, 30))
        nh_end = datetime.combine(day, time(11, 30))
        for sym, trades in trades_by_day[day].items():
            first_hour_trades = [trade for trade in trades if fh_start <= trade['time'] < fh_end]
            next_hour_trades = [trade for trade in trades if fh_end <= trade['time'] < nh_end]
            if first_hour_trades and next_hour_trades:
                avg_first = sum(t['price'] for t in first_hour_trades) / len(first_hour_trades)
                avg_next = sum(t['price'] for t in next_hour_trades) / len(next_hour_trades)
                ret = (avg_next - avg_first) / avg_first
                first_hour_returns.append(ret)
    if first_hour_returns:
        overall_return = sum(first_hour_returns) / len(first_hour_returns)
    else:
        overall_return = 0
    print(f"\nAverage First Hour Return: {overall_return*100:.2f}%")
    
if __name__ == '__main__':
    orders_file = 'past_month_orders.json'
    analyze_orders(orders_file)
    calculate_average_overnight_return(orders_file)
    calculate_first_hour_return(orders_file)
