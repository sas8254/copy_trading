"""WebSocket consumer for the web UI's live event feed."""

import json
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

GROUP = "dashboard"


@database_sync_to_async
def _user_for_token(token: str):
    """Validate a Knox token (sent as ?token=..., since browsers can't set
    headers on WebSocket connections). Returns the user or None."""
    from knox.auth import TokenAuthentication
    from rest_framework.exceptions import AuthenticationFailed

    if not token:
        return None
    try:
        user, _ = TokenAuthentication().authenticate_credentials(token.encode())
    except AuthenticationFailed:
        return None
    return user


class DashboardConsumer(AsyncWebsocketConsumer):
    """Streams trade/copy/alert/reconcile events to logged-in browsers."""

    async def connect(self):
        query = parse_qs(self.scope.get("query_string", b"").decode())
        user = await _user_for_token((query.get("token") or [""])[0])
        if user is None:
            await self.close(code=4401)
            return
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def dashboard_event(self, event):
        await self.send(text_data=json.dumps(event.get("payload", {}), default=str))
