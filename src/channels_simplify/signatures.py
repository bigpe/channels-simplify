import dataclasses
import json
from dataclasses import dataclass
from typing import Union, Any
from django.contrib.auth import get_user_model
from django.core.cache import cache

User = get_user_model()


class Payload:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __str__(self):
        return self.serialize()

    def serialize(self):
        return self.__dict__


class ResponsePayload:
    """List of response payload signatures"""

    @dataclass
    class ChannelLayerDisabled(Payload):
        #: Error message
        message: str = 'Channel layer disabled, modify your settings, is requirement for broadcast correct work ' \
                       'see more about it https://channels.readthedocs.io/en/stable/topics/channel_layers.html'

    @dataclass
    class ActionNotExist(Payload):
        message: str = 'Event not exist'  #: Error message

    @dataclass
    class PayloadSignatureWrong(Payload):
        required: str  #: Hint about missing signature
        message: str = 'Payload signature wrong'  #: Error message

    @dataclass
    class ActionSignatureWrong(Payload):
        unexpected: str  #: Hint about unexpected signature
        message: str = 'Event signature wrong'  #: Error message

    @dataclass
    class RecipientNotExist(Payload):
        message: str = 'Recipient not exist'  #: Error message

    @dataclass
    class RecipientIsMe(Payload):
        message: str = 'You cannot be the recipient'  #: Error message

    @dataclass
    class SomethingWrong(Payload):
        error_text: str  #: Text of error
        error_hash: str  #: Hash of error
        message: str = 'Something wrong'  #: Error message

    @dataclass
    class Error(Payload):
        message: str  #: Error message


class EventsEnum:
    """List of existed events"""
    error = 'error'  #: :func:`SimpleConsumer.error`


@dataclass
class EventSystem:
    initiator_channel: str = None  #: Event initiator channel name
    initiator_user_id: int = None  #: Event initiator user id
    event_id: str = None

    def serialize(self):
        return {
            'initiator_channel': self.initiator_channel,
            'initiator_user_id': self.initiator_user_id,
            'event_id': self.event_id,
        }


class BaseEvent:
    @staticmethod
    def serialize_payload(payload: [dict, Payload]) -> dict:
        return payload.serialize() if isinstance(payload, Payload) else payload

    @staticmethod
    def serialize_system(system: [dict, EventSystem]) -> dict:
        return system.serialize() if isinstance(system, EventSystem) else system


@dataclass
class Event(BaseEvent):
    """Event signature for request and response"""
    name: str  #: Event's name
    system: Union[EventSystem, dict]  #: System name information
    payload: Union[Payload, dict] = dataclasses.field(default_factory=dict)  #: Event's payload

    def __str__(self, to_json=True):
        return self.serialize(to_json=True)

    def serialize(self, to_json=False, to_channels=False, pop_system=False):
        if to_channels:
            data = EventChannels(
                type=self.name,
                payload=self.serialize_payload(self.payload),
                system=self.serialize_system(self.system)
            ).serialize()
        else:
            data = {
                'event': self.name,
                'payload': self.serialize_payload(self.payload),
                'system': self.serialize_system(self.system)
            }
        data.pop('system') if pop_system else ...
        data = json.dumps(data, default=lambda o: o.__dict__) if to_json else data
        return data

    def to_channels(self):
        return self.serialize(to_channels=True)

    def to_json(self):
        return self.serialize(to_json=True)


@dataclass
class EventChannels(BaseEvent):
    type: str  #: Handler's name
    payload: Union[Payload, dict]  #: Handler's payload
    system: Union[EventSystem, dict]  #: System handler information

    def serialize(self):
        return {
            'type': self.type,
            'payload': self.serialize_payload(self.payload),
            'system': self.serialize_system(self.system)
        }


@dataclass
class MessageSystem:
    initiator_channel: str  #: Initiator channel name
    receiver_channel: str  #: Receiver channel name
    initiator_user_id: int  #: Initiator user id
    event_id: str  #: Event id

    def serialize(self):
        return {
            'initiator_channel': self.initiator_channel,
            'initiator_user_id': self.initiator_user_id,
            'event_id': self.event_id,
        }


class TargetsEnum:
    """Broadcast targets"""
    for_all = 'for_all'  #: For all users in broadcast group
    for_user = 'for_user'  #: For specific user (lookup by specific key)
    for_initiator = 'for_initiator'  #: For initiator user only


class LookupUser:
    Fields = ['id', 'username']

    to_id: int = None  #: Message target user id
    to_username: str = None  #: Message target user username

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def serialize(self):
        lookup = {field: getattr(self, f'to_{field}', None) for field in self.Fields}
        lookup = dict(filter(lambda field: field[1], lookup.items()))
        return lookup


@dataclass
class Message:
    user: User  #: User who receive content
    system: MessageSystem  #: System content information
    target: TargetsEnum  #: Target for broadcast
    lookup: LookupUser  #: Lookup user fields
    target_resolver: dict  #: Target resolver
    payload: Payload  #: Payload
    consumer: Any  #: Consumer object

    @property
    def is_target(self):
        return self.target_resolver.get(self.target, lambda _: False)(self)

    @property
    def is_initiator(self):
        return self.system.initiator_channel == self.system.receiver_channel

    @property
    def initiator_user(self) -> User:
        return User.objects.filter(id=self.system.initiator_user_id).first()

    @property
    def target_user(self) -> User:
        return User.objects.filter(**self.lookup.serialize()).first()

    @staticmethod
    def cache_set(key, value, ttl):
        cache.set(key, value, ttl)

    @staticmethod
    def cache_get(key):
        return cache.get(key)

    @staticmethod
    def cache_delete(key):
        cache.delete(key)

    @property
    def before_key(self):
        return f'consumer-before-{self.system.event_id, self.system.initiator_channel}'

    @property
    def before_activated(self):
        return self.cache_get(self.before_key)

    def before_activate(self):
        self.cache_set(self.before_key, True, 180)

    def before_drop(self):
        self.cache_delete(self.before_key)


def for_initiator(message: Message):
    return message.target == TargetsEnum.for_initiator and message.is_initiator


def for_all(message: Message):
    return message.target == TargetsEnum.for_all and not message.is_initiator


def for_user(message: Message):
    if message.target == TargetsEnum.for_user:
        lookup_user = User.objects.filter(**message.lookup.serialize()).first()
        return message.user == lookup_user
    return False


TargetResolver = {
    TargetsEnum.for_initiator: for_initiator,
    TargetsEnum.for_all: for_all,
    TargetsEnum.for_user: for_user
}
