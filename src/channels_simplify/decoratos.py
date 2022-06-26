import re
import sys
import traceback
from functools import wraps
from hashlib import md5
from typing import Callable

from .signatures import ResponsePayload, EventSystem, EventsEnum, Event, Message, Payload


def auth(f):
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        from .consumers import SimpleConsumer
        self: SimpleConsumer
        user = self.get_user()
        if not self.authed:
            self.accept()
            return f(self, *args, **kwargs)
        if user.is_anonymous:
            self.close()
        self.accept()
        return f(self, *args, **kwargs)

    wrapper.__doc__ = f.__doc__
    return wrapper


def check_recipient_not_me(f):
    @wraps(f)
    def wrapper(self, message: Message, payload: Payload, *args, **kwargs):
        from .consumers import SimpleEvent
        self: SimpleEvent
        if message.target_user != message.initiator_user:
            return f(self, message, payload, *args, **kwargs)
        else:
            action = Event(
                name=EventsEnum.error,
                payload=ResponsePayload.RecipientIsMe().serialize(),
                system=EventSystem(**message.system.serialize())
            )
            return action

    wrapper.__doc__ = f.__doc__
    return wrapper


def safe(f: Callable) -> Callable:
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        from .consumers import SimpleConsumer
        self: SimpleConsumer
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
            self.Error(
                consumer=self,
                payload=ResponsePayload.SomethingWrong(
                    error_text=error,
                    error_hash=tb_hash
                )).fire()

    wrapper.__doc__ = f.__doc__
    return wrapper
