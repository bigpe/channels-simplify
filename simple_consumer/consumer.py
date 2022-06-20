"""
Websocket: Simple Consumer
====================================
Simple websocket consumer
"""

import uuid
from typing import Callable

from asgiref.sync import async_to_sync
from channels.consumer import get_handler_name
from channels.generic.websocket import JsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.core.cache import cache

from .decoratos import auth, safe
from .signatures import ResponsePayload, BasePayload, ActionsEnum, Action, TargetsEnum, Message, ActionSystem, \
    MessageSystem, TargetResolver
from .utils import camel_to_snake, user_cache_key, camel_to_dot

User = get_user_model()


class SimpleEvent:
    request_payload_type = BasePayload  #: Payload type for request this event from client side
    response_payload_type = BasePayload  #: Payload type for both (who send/and who must receive)
    response_payload_type_initiator = BasePayload  #: Payload type for users who send this event from client side
    response_payload_type_target = BasePayload  #: Payload type for users who access to receive this event
    target = TargetsEnum.for_all  #: Who must receive this event
    consumer = None  #: Consumer object instance
    hidden = False  #: If hidden, event can't be called from client side

    def __init__(self, event=None, payload: BasePayload = BasePayload()):
        self.consumer: SimpleConsumer

        event_name = camel_to_dot(self.__class__.__name__)

        # If event data not provided, it means event instance was called directly, you can provide payload
        # to imitate client side communicate, event type (name) and system data obtained automatically
        if not event:
            self.hidden = False
            event = {
                'type': event_name,
                'payload': payload.to_data(),
                'system': self.consumer.get_systems().to_data()
            }

        self.event = event

        # If event marked as Hidden, send action not exist
        if self.hidden:
            action = Action(
                event=ActionsEnum.error,
                payload=ResponsePayload.ActionNotExist().to_data(),
                system=ActionSystem()
            )
            self.consumer.send_json(content=action.to_data())
            return

        # Send broadcast
        self.consumer.send_broadcast(
            event,
            action_for_target=self.action_for_target,
            action_for_initiator=self.action_for_initiator,
            target=self.target,
            before_send=self.before_send,
            payload_type=self.request_payload_type
        )

    """
    Do something before event well be sent to initiator or target users
    Use if you need mutate DB data before users receive event
    """

    def before_send(self, message: Message, payload: request_payload_type):
        ...

    """
    Do something for user who send this event from client side
    Returned Action well be fired and sent
    """

    def action_for_initiator(self, message: Message, payload: request_payload_type) -> [Action, None]:
        ...

    """
    Do something for user who access to receive this event
    Returned Action well be fired and sent
    """

    def action_for_target(self, message: Message, payload: request_payload_type) -> [Action, None]:
        ...


class SimpleConsumer(JsonWebsocketConsumer):
    broadcast_group = None  #: Group to join after connect
    authed = True  #: Check connected user is authed, if not - close connect
    custom_target_resolver = {}  #: If you need define rules for lookup users who want to receive events (target)

    def __init__(self):
        super(SimpleConsumer, self).__init__()
        self.inject_consumer_to_events()

    @auth
    def connect(self):
        self.cache_system()
        self.join_group(self.broadcast_group)
        self.after_connect()

    def after_connect(self):
        ...

    def before_disconnect(self):
        ...

    def disconnect(self, code):
        self.before_disconnect()

    def send_json(self, content, close=False):
        if 'system' in content:
            content.pop('system')
        super(SimpleConsumer, self).send_json(content, close)

    def cache_system(self):
        cache.set(user_cache_key(self.get_user()), self.get_systems().to_data(), 40 * 60)

    def get_user(self, user_id: int = None) -> User:
        return User.objects.get(id=user_id) if user_id else self.scope.get('user', AnonymousUser())

    def join_group(self, group_name: str):
        if group_name:
            async_to_sync(self.channel_layer.group_add)(group_name, self.channel_name)

    def leave_group(self, group_name: str):
        if group_name:
            async_to_sync(self.channel_layer.group_discard)(group_name, self.channel_name)

    def get_systems(self) -> ActionSystem:
        return ActionSystem(
            initiator_channel=self.channel_name,
            initiator_user_id=self.scope['user'].id,
            action_id=str(uuid.uuid4())
        )

    @safe
    def receive(self, *arg, **kwargs):
        super().receive(*arg, **kwargs)

    @safe
    def send(self, *arg, **kwargs):
        super().send(*arg, **kwargs)

    def receive_json(self, content, **kwargs):
        if self.broadcast_group:
            action, error = self.check_signature(lambda: Action(**content, system=self.get_systems()))
            if error:
                return
            if action:
                action_handler = getattr(self, get_handler_name(action.to_system_data()), None)
                if not action_handler:
                    action = Action(
                        event=ActionsEnum.error,
                        payload=ResponsePayload.ActionNotExist().to_data(),
                        system=self.get_systems()
                    )
                    self.send_json(content=action.to_data())
                    return
                async_to_sync(self.channel_layer.group_send)(self.broadcast_group, action.to_system_data())

    def send_to_group(self, action: Action, group_name: str = None):
        async_to_sync(
            self.channel_layer.group_send
        )(self.broadcast_group if not group_name else group_name, action.to_system_data())

    def check_signature(self, f: Callable):
        error = False
        data = None
        try:
            data = f()
        except TypeError as e:
            if ' missing ' in str(e):
                required = str(e).split('argument: ')[1].strip().replace("'", '')
                action = Action(
                    event=ActionsEnum.error,
                    payload=ResponsePayload.PayloadSignatureWrong(required=required).to_data(),
                    system=self.get_systems()
                )
                self.send_json(content=action.to_data())
                error = True
            if ' unexpected ' in str(e):
                unexpected = str(e).split('argument')[1].strip().replace("'", '')
                action = Action(
                    event=ActionsEnum.error,
                    payload=ResponsePayload.ActionSignatureWrong(unexpected=unexpected).to_data(),
                    system=self.get_systems()
                )
                self.send_json(content=action.to_data())
                error = True
        return data, error

    def parse_payload(self, event, payload_type: BasePayload()):
        payload = BasePayload(**event['payload'])
        error = False
        if payload_type:
            payload, error = self.check_signature(lambda: payload_type(**payload.to_data()))
        return payload, error

    @safe
    def send_broadcast(self, event, action_for_target: Callable = None, action_for_initiator: Callable = None,
                       target=TargetsEnum.for_all, before_send: Callable = None,
                       system_before_send: Callable = None, payload_type: BasePayload() = None):

        payload, error = self.parse_payload(event, payload_type)
        if error:
            return

        # TODO kwargs lookup for to_user_id/to_username
        message = Message(
            to_user_id=payload.to_data().pop('to_user_id'),
            to_username=payload.to_data().pop('to_username'),
            payload=payload,
            system=MessageSystem(
                **ActionSystem(**event['system']).to_data(),
                receiver_channel=self.channel_name
            ),
            user=self.scope['user'],
            target=target,
            target_resolver=TargetResolver.__dict__.update(self.custom_target_resolver)
        )

        if system_before_send:
            system_before_send()

        if (message.target == TargetsEnum.for_user and not message.target_user) and message.is_initiator:
            action = Action(
                event=ActionsEnum.error,
                payload=ResponsePayload.RecipientNotExist().to_data(),
                system=ActionSystem(**message.system.to_data())
            )
            self.send_json(content=action.to_data())
            return  # Interrupt action for initiator and action for target if recipient not found

        def before():
            if before_send and not message.before_send_activated:
                act: Action = before_send(message, payload)
                if act:
                    self.send_json(content=act.to_data())
                message.before_send_activate()
                return True
            return False

        if message.is_initiator and action_for_initiator:
            activated = before()
            action: Action = action_for_initiator(message, payload)
            if action:
                self.send_json(content=action.to_data())
            if message.before_send_activated and not activated:
                message.before_send_drop()

        if message.is_target and action_for_target:
            activated = before()
            action: Action = action_for_target(message, payload)
            if action:
                self.send_json(content=action.to_data())
            if message.before_send_activated and not activated:
                message.before_send_drop()

    def inject_consumer_to_events(self):
        attributes = list(filter(lambda attr: not attr.startswith('_') and not attr.startswith('__'), dir(self)))
        classes = list(filter(lambda cls: hasattr(getattr(self, cls), '__base__'), attributes))
        events = list(filter(lambda e: issubclass(getattr(self, e), SimpleEvent), classes))
        for event in events:
            event_class = getattr(self, event)
            hidden = False
            if hasattr(event_class, 'hidden'):
                if event_class.hidden:
                    hidden = True
            event_class.consumer = self
            if not hidden:
                setattr(self, camel_to_snake(event), event_class)

    class Error(SimpleEvent):
        """Show error message"""
        request_payload_type = ResponsePayload.Error

        def action_for_initiator(self, message: Message, payload: request_payload_type):
            return Action(
                event=ActionsEnum.error,
                payload=ResponsePayload.Error(message=payload.message).to_data(),
                system=self.event['system']
            )
