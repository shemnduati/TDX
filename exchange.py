import ccxt
from config import API_KEY, SECRET

def get_exchange():
    exchange = ccxt.binance({
    "apiKey": API_KEY,
    "secret": SECRET,
    "enableRateLimit": True,
    "options": {
            "adjustForTimeDifference": True
        },
        "recvWindow": 10000 
    })
    return exchange