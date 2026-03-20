import asyncio
import websockets

async def hello():
    uri = 'ws://127.0.0.1:10000/ws/debug123'
    print(f'Attempting connection to {uri}...')
    try:
        async with websockets.connect(uri) as websocket:
            print('Connected!')
    except websockets.exceptions.InvalidStatusCode as e:
        print(f'Status Code Error: {e.status_code}')
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(hello())
