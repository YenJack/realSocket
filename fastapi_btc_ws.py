import asyncio
import json
import random
import time
from datetime import datetime
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()

# --- Configuration ---
UPDATE_INTERVAL_SECONDS = 1.0
START_PRICE = 60000.0
VOLATILITY = 0.0015

# --- Connection Manager ---
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
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                try:
                    await connection.close()
                except Exception:
                    pass
                self.disconnect(connection)

manager = ConnectionManager()

current_price = START_PRICE
last_update_ts = time.time()

# --- Background price simulator ---
async def price_simulator():
    global current_price, last_update_ts
    while True:
        shock = random.gauss(0, 1)
        fraction_move = VOLATILITY * shock * (UPDATE_INTERVAL_SECONDS ** 0.5)
        current_price = max(0.01, current_price * (1 + fraction_move))
        last_update_ts = time.time()

        payload = {
            "symbol": "BTC",
            "currency": "USD",
            "price": round(current_price, 2),
            "timestamp": int(last_update_ts),
            "iso": datetime.utcfromtimestamp(last_update_ts).isoformat() + "Z"
        }
        message = json.dumps(payload)
        await manager.broadcast(message)
        await asyncio.sleep(UPDATE_INTERVAL_SECONDS)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(price_simulator())

# --- WebSocket endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # send initial snapshot
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
                await websocket.send_text(json.dumps({"type": "ping"}))
                continue

            if data.lower().strip() == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "timestamp": int(time.time())}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# --- REST endpoint ---
@app.get("/price")
async def get_price():
    return JSONResponse({
        "symbol": "BTC",
        "currency": "USD",
        "price": round(current_price, 2),
        "timestamp": int(last_update_ts),
        "iso": datetime.utcfromtimestamp(last_update_ts).isoformat() + "Z"
    })

# --- HTML test page ---
@app.get("/")
async def index():
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
      const log = (m) => {
        const p = document.getElementById('log');
        p.textContent = m + "\\n" + p.textContent;
      };
      const status = document.getElementById('status');

      const ws = new WebSocket('wss://' + location.host + '/ws');

      ws.onopen = () => { status.textContent = 'connected'; };
      ws.onmessage = (ev) => { log(ev.data); };
      ws.onclose = () => { status.textContent = 'closed'; };
      ws.onerror = (e) => { status.textContent = 'error'; console.error(e); };
    </script>
  </body>
</html>
"""
    return HTMLResponse(html)
