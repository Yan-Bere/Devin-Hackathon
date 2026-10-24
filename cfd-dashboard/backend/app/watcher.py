import asyncio


class WebSocketHub:
    def __init__(self):
        self.connections = set()

    async def connect(self, websocket):
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket):
        self.connections.discard(websocket)

    async def broadcast(self, message):
        stale = []
        for connection in tuple(self.connections):
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)


class DirectoryWatcher:
    def __init__(self, store, hub):
        self.store = store
        self.hub = hub
        self.task = None

    async def poll_once(self):
        for message in self.store.scan():
            await self.hub.broadcast(message)

    async def run(self):
        while True:
            await self.poll_once()
            await asyncio.sleep(max(0.1, self.store.cfg.poll_interval))

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
