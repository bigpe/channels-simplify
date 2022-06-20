import re
import sys
import traceback
from functools import wraps
from hashlib import md5
from typing import Callable

from channels.generic.websocket import JsonWebsocketConsumer

from .signatures import ResponsePayload, ActionSystem, ActionsEnum, Action, Message, BasePayload


def auth(f):
    def wrapper(self, *args, **kwargs):
        try:
            user = self.get_user()
            if not self.authed:
                self.accept()
                return f(self)
            if user.is_anonymous:
                self.close()
            self.accept()
            return f(self)
        except Exception:
            ...

    wrapper.__doc__ = f.__doc__
    return wrapper


def check_auth(f):
    def wrapper(self, *args, **kwargs):
        try:
            user = self.get_user()
            if not user.is_anonymous:
                return f(self, *args, **kwargs)
        except Exception:
            ...

    wrapper.__doc__ = f.__doc__
    return wrapper


def check_payload(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except AttributeError as e:
            required_payload = str(e).split('attribute')[1].strip().replace("'", '')
            event = {
                'system': self.get_systems().to_data(),
                'payload': {}
            }

            def action_for_initiator(message: Message, payload):
                return Action(
                    event=ActionsEnum.error,
                    payload=ResponsePayload.PayloadSignatureWrong(required=required_payload).to_data(),
                    system=self.get_systems()
                )

            self.send_broadcast(event, action_for_initiator=action_for_initiator)

    wrapper.__doc__ = f.__doc__
    return wrapper


def check_recipient(f):
    def wrapper(message: Message, payload: BasePayload, *args, **kwargs):
        if message.target_user:
            return f(message, payload, *args, **kwargs)
        else:
            action = Action(
                event=ActionsEnum.error,
                payload=ResponsePayload.RecipientNotExist().to_data(),
                system=ActionSystem(**message.system.to_data())
            )
            return action

    wrapper.__doc__ = f.__doc__
    return wrapper


def check_recipient_not_me(f):
    def wrapper(message: Message, payload: BasePayload, *args, **kwargs):
        if message.target_user != message.initiator_user:
            return f(message, payload, *args, **kwargs)
        else:
            action = Action(
                event=ActionsEnum.error,
                payload=ResponsePayload.RecipientIsMe().to_data(),
                system=ActionSystem(**message.system.to_data())
            )
            return action

    wrapper.__doc__ = f.__doc__
    return wrapper


def safe(f: Callable) -> Callable:
    @wraps(f)
    def wrapper(self: JsonWebsocketConsumer, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except Exception as err:
            error = f'{err.__class__.__name__}: {str(err)}'
            traceback.print_exception(*sys.exc_info())
            tb = traceback.format_exc()
            lines = re.findall(r'line \d*, ', tb)
            for line in lines:
                tb = tb.replace(line, '')
            tb_hash = md5(tb.encode('utf-8')).hexdigest()
            self.send_json(content={'error': 'Something wrong', 'error_message': error, 'error_hash': tb_hash})

    wrapper.__doc__ = f.__doc__
    return wrapper
