"""
TELE-CARE WebRTC Signaling Server
Run: python signaling_server.py
Requires: pip install fastapi uvicorn websockets
"""

import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost",
        "https://telecareai.site",
        "https://www.telecareai.site",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# rooms[room_id] = { "patient": ws | None, "doctor": ws | None }
rooms: dict = {}

def get_room(room_id: str) -> dict:
    if room_id not in rooms:
        rooms[room_id] = {"patient": None, "doctor": None}
    return rooms[room_id]

def cleanup_room(room_id: str):
    if room_id in rooms:
        r = rooms[room_id]
        if r["patient"] is None and r["doctor"] is None:
            del rooms[room_id]

@app.websocket("/ws/{room_id}/{role}")
async def signaling(ws: WebSocket, room_id: str, role: str):
    if role not in ("patient", "doctor"):
        await ws.close(code=1008)
        return

    await ws.accept()
    room = get_room(room_id)

    # Disconnect old connection for same role if exists
    old = room.get(role)
    if old:
        try:
            await old.close()
        except Exception:
            pass

    room[role] = ws
    peer_role = "doctor" if role == "patient" else "patient"

    print(f"[{room_id}] {role} connected  (rooms active: {len(rooms)})")

    # Notify both peers: this role is connected (handles reconnects too)
    # Send to newly connected: other peer is here
    if room[peer_role]:
        await ws.send_text(json.dumps({"type": "peer_joined", "role": peer_role}))
        # ALSO send to the other peer: this role just joined/rejoined
        try:
            await room[peer_role].send_text(json.dumps({"type": "peer_joined", "role": role}))
        except Exception:
            pass
    else:
        # Other peer not here yet, but this one is connected
        # When other joins later, they'll get notified
        pass

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg["from"] = role  # tag who sent it

            peer_ws = room.get(peer_role)
            if peer_ws:
                await peer_ws.send_text(json.dumps(msg))
            else:
                # Peer not connected yet — send back a notice
                await ws.send_text(json.dumps({
                    "type": "error",
                    "message": f"Waiting for {peer_role} to join…"
                }))
    except WebSocketDisconnect:
        room[role] = None
        print(f"[{room_id}] {role} disconnected")
        peer_ws = room.get(peer_role)
        if peer_ws:
            try:
                await peer_ws.send_text(json.dumps({"type": "peer_left", "role": role}))
            except Exception:
                pass
        cleanup_room(room_id)

@app.get("/health")
def health():
    return {"status": "ok", "active_rooms": len(rooms)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("signaling_server:app", host="0.0.0.0", port=8765, reload=False)