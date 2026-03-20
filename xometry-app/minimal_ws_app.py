from fastapi import FastAPI, WebSocket
import uvicorn

app = FastAPI()

@app.websocket('/ws')
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text('Hello')
    try:
        while True:
            await websocket.receive_text()
    except:
        pass

if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=10001)
