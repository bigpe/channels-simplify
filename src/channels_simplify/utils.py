import re

from django.contrib.auth import get_user_model
from django.core.cache import cache

User = get_user_model()


def camel_to_snake(name):
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


def snake_to_dot(name):
    return name.replace('_', '.')


def camel_to_dot(name):
    return snake_to_dot(camel_to_snake(name))


def dot_to_camel(name):
    components = name.split('.')
    return components[0] + ''.join(x.title() for x in components[1:])


def dot_to_snake(name):
    return name.replace('.', '_')


def snake_to_camel(name):
    components = name.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


def user_cache_key(user: User):
    return f'channels-simplify-user-{user.id}'


def get_system_cache(user: User):
    return cache.get(user_cache_key(user), {})
