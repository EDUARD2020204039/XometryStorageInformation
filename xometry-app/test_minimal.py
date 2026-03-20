import asyncio
import websockets

async def hello():
    uri = 'ws://127.0.0.1:10001/ws'
    try:
        async with websockets.connect(uri) as websocket:
            msg = await websocket.recv()
            print(f'Received: {msg}')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(hello())
