# fastapi_btc_ws.py
# Simple FastAPI WebSocket service that simulates live Bitcoin price updates
# - Serves a small test HTML page at GET /
# - REST endpoint GET /price returns current price
# - WebSocket endpoint /ws pushes JSON messages to all connected clients
# Run: pip install fastapi uvicorn
#      python fastapi_btc_ws.py

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI()

# --- Configuration ---
UPDATE_INTERVAL_SECONDS = 1.0  # how often the server updates price and broadcasts
START_PRICE = 60000.0  # starting simulated BTC price
VOLATILITY = 0.0015  # typical fractional move per tick (adjust for bigger/smaller swings)

# --- runtime state ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: str):
        # copy list to avoid mutation during iteration
        conns = list(self.active_connections)
        for connection in conns:
            try:
                await connection.send_text(message)
            except Exception:
                # if sending fails, drop connection
                try:
                    await connection.close()
                except Exception:
                    pass
                self.disconnect(connection)

manager = ConnectionManager()

current_price = START_PRICE
last_update_ts = time.time()

# --- price simulation background task ---
async def price_simulator():
    global current_price, last_update_ts
    while True:
        # simple geometric random walk step
        drift = 0.0
        shock = random.gauss(0, 1)
        fraction_move = drift * UPDATE_INTERVAL_SECONDS + VOLATILITY * shock * (UPDATE_INTERVAL_SECONDS ** 0.5)
        current_price = max(0.01, current_price * (1 + fraction_move))
        last_update_ts = time.time()

        # prepare message
        payload = {
            "symbol": "BTC",
            "currency": "USD",
            "price": round(current_price, 2),
            "timestamp": int(last_update_ts),
            "iso": datetime.utcfromtimestamp(last_update_ts).isoformat() + "Z"
        }
        message = json.dumps(payload)

        # broadcast to websockets
        await manager.broadcast(message)

        await asyncio.sleep(UPDATE_INTERVAL_SECONDS)

# start background task on app startup
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(price_simulator())

# --- WebSocket endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "snapshot",
            "symbol": "BTC",
            "price": round(current_price, 2),
            "timestamp": int(last_update_ts)
        }))
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # send a ping to keep alive
                await websocket.send_text(json.dumps({"type": "ping"}))
                continue

            if data.lower().strip() == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "timestamp": int(time.time())}))
            else:
                # ignore unknown messages
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# --- REST endpoints ---
@app.get("/price")
async def get_price():
    return JSONResponse({
        "symbol": "BTC",
        "currency": "USD",
        "price": round(current_price, 2),
        "timestamp": int(last_update_ts),
        "iso": datetime.utcfromtimestamp(last_update_ts).isoformat() + "Z"
    })

@app.get("/")
async def index():
    # Simple HTML page to test websocket in browser
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>BTC WS Test</title>
  </head>
  <body>
    <h1>Simulated BTC Price WebSocket</h1>
    <div id="status">connecting...</div>
    <pre id="log" style="height:400px;overflow:auto;border:1px solid #ccc;padding:8px"></pre>
    <script>
      const log = (m)=>{ const p=document.getElementById('log'); p.textContent = m + "\n" + p.textContent };
      const status = document.getElementById('status');
      const ws = new WebSocket('wss://' + location.host + '/ws');
      ws.onopen = ()=>{ status.textContent = 'connected'; };
      ws.onmessage = (ev)=>{ log(ev.data); };
      ws.onclose = ()=>{ status.textContent = 'closed'; };
      ws.onerror = (e)=>{ status.textContent = 'error'; console.error(e); };
    </script>
  </body>
</html>
"""
    return HTMLResponse(html)

# --- run as script ---
#if __name__ == "__main__":
    # install dependencies: pip install fastapi uvicorn
    #uvicorn.run("fastapi_btc_ws:app", host="0.0.0.0", port=8000, reload=False)
