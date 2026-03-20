import asyncio
import websockets

async def hello():
    uri = 'ws://127.0.0.1:10000/ws/debug123'
    print(f'Attempting connection to {uri} with Origin...')
    try:
        async with websockets.connect(uri, extra_headers={"Origin": "http://localhost"}) as websocket:
            print('Connected successfully!')
    except Exception as e:
        print(f'Failed: {e}')

if __name__ == "__main__":
    asyncio.run(hello())
