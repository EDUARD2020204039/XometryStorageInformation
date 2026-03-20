import asyncio
import websockets
import requests
import json
import time
import threading

PART_ID = '720470'
WS_URL = f'ws://127.0.0.1:10000/ws/{PART_ID}'
API_URL = 'http://127.0.0.1:10000/api/extension/analyze'

async def listen():
    print(f'Connecting to {WS_URL}...')
    async with websockets.connect(WS_URL) as websocket:
        print('Connected to WebSocket. Waiting for messages...')
        while True:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=25.0)
                print(f'Received WS Message: {message}')
                break
            except asyncio.TimeoutError:
                print('Timeout waiting for message.')
                break

def trigger_analysis():
    time.sleep(2) # Give WS time to connect
    print(f'Triggering analysis via API...')
    payload = {'part_id': PART_ID}
    response = requests.post(API_URL, json=payload)
    print(f'API Response: {response.json()}')

async def main():
    # Start trigger in parallel
    trigger_thread = threading.Thread(target=trigger_analysis)
    trigger_thread.start()
    
    await listen()
    trigger_thread.join()

if __name__ == '__main__':
    asyncio.run(main())
