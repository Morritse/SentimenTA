import json
import subprocess
from datetime import datetime, timedelta

def get_orders_for_date(date):
    # Format date for API
    date_str = date.strftime('%Y-%m-%d')
    next_date = (date + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Construct curl command
    cmd = [
        'curl',
        '-H', 'APCA-API-KEY-ID: PKKM4HD8KZORIEC0DLGG',
        '-H', 'APCA-API-SECRET-KEY: IXkOeMg7mlKfW53DAWmm1gKjZJypTgZvLZqMJRcL',
        f'https://paper-api.alpaca.markets/v2/orders?status=closed&after={date_str}&before={next_date}&limit=500'
    ]
    
    # Execute curl command and capture output
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)

# Get orders for the past month
end_date = datetime(2025, 2, 14).date()  # Yesterday
start_date = end_date - timedelta(days=30)
current_date = start_date

all_orders = []
print("Fetching orders...")

while current_date <= end_date:
    print(f"Getting orders for {current_date}...")
    daily_orders = get_orders_for_date(current_date)
    all_orders.extend(daily_orders)
    current_date += timedelta(days=1)

print(f"Found {len(all_orders)} total orders")

# Save all orders to file
with open('past_month_orders.json', 'w') as f:
    json.dump(all_orders, f)

print("Saved orders to past_month_orders.json")
