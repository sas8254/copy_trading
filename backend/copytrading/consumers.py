"""WebSocket consumers for the copy-trading dashboard."""

import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

GROUP = "dashboard"


class DashboardConsumer(AsyncWebsocketConsumer):
    """Pushes live trade/copy/alert/reconcile events to the browser.

    On connect it sends a one-time snapshot of current state, then streams
    every event broadcast to the 'dashboard' group.
    """

    async def connect(self):
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({"type": "snapshot", **(await self._snapshot())}))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def dashboard_event(self, event):
        await self.send(text_data=json.dumps(event.get("payload", {})))

    @sync_to_async
    def _snapshot(self):
        from .models import Alert, BrokerAccount, CopyOrder

        accounts = [
            {
                "label": a.label,
                "role": a.role,
                "active": a.active,
                "has_token": bool(a.access_token),
            }
            for a in BrokerAccount.objects.all()
        ]
        alerts = [
            {
                "kind": a.kind,
                "message": a.message,
                "count": a.count,
                "account": a.account.label if a.account else None,
            }
            for a in Alert.objects.filter(resolved=False)[:50]
        ]
        copy_orders = [
            {
                "symbol": c.trade.tradingsymbol,
                "qty": c.computed_quantity,
                "status": c.status,
                "copy": c.mapping.copy.label,
                "broker_order_id": c.broker_order_id,
            }
            for c in CopyOrder.objects.select_related("trade", "mapping__copy")[:30]
        ]
        return {"accounts": accounts, "alerts": alerts, "copy_orders": copy_orders}


# Kept for backwards-compat / simple connectivity testing.
class EchoConsumer(AsyncWebsocketConsumer):
    group_name = GROUP

    async def connect(self):
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({"type": "connected"}))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        await self.send(text_data=json.dumps({"type": "echo", "data": text_data}))

    async def dashboard_event(self, event):
        await self.send(text_data=json.dumps(event.get("payload", {})))
