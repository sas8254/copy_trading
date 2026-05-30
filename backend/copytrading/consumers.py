"""WebSocket consumers for the copy-trading dashboard."""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class EchoConsumer(AsyncWebsocketConsumer):
    """Smoke-test consumer: echoes messages and joins the dashboard group.

    Verifies the outbound Channels path end to end. The real dashboard consumer
    will subscribe to trade/position/alert events broadcast to the group.
    """

    group_name = "dashboard"

    async def connect(self):
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({"type": "connected"}))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        await self.send(text_data=json.dumps({"type": "echo", "data": text_data}))

    async def dashboard_event(self, event):
        """Handler for messages broadcast to the 'dashboard' group."""
        await self.send(text_data=json.dumps(event.get("payload", {})))
