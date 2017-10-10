from orator.orm import model

from sea import current_app
from sea.utils import import_string
from sea.contrib.extensions.cache import default_key, CacheNone
from orator.exceptions.orm import ModelNotFound


def _model_cache_key(f, cls, *args, **kwargs):
    return default_key(cls, *args, **kwargs)


def _related_caches_key(cls, id):
    return 'related_caches.{}.{}.{}'.format(
        cls.__module__, cls.__name__, id)


def _register_to_related_caches(f, id, cls, *args, **kwargs):
    cache = current_app().extensions['cache']
    key = cache._backend.trans_key(_related_caches_key(cls, id))
    redis = cache._backend._client
    cached_key = cache._backend.trans_key(
        f.make_cache_key(cls, *args, **kwargs))
    redis.sadd(key, cached_key)
    redis.expire(key, cache._backend.default_ttl)
    return True


def _find_register(f, ins, cls, *args, **kwargs):
    return _register_to_related_caches(f, args[0], cls, *args, **kwargs)


def _find_by_register(f, ins, cls, *args, **kwargs):
    if ins is None or ins is CacheNone:
        return True
    return _register_to_related_caches(f, ins.id, cls, *args, **kwargs)


def _bulk_register_to_related_caches(cls, key_model_map):
    cache = current_app().extensions['cache']
    redis = cache._backend._client
    for cached_key, ins in key_model_map.items():
        key = cache._backend.trans_key(_related_caches_key(cls, ins.id))
        cached_key = cache._backend.trans_key(cached_key)
        redis.sadd(key, cached_key)
        redis.expire(key, cache._backend.default_ttl)
    return True


def _clear_related_caches(instance):
    cache = current_app().extensions['cache']
    key = cache._backend.trans_key(
        _related_caches_key(instance.__class__, instance.id))
    redis = cache._backend._client
    related_caches = redis.smembers(key)
    if related_caches:
        redis.delete(*related_caches)
    return True


def _id_is_list(cls, id, *args, **kwargs):
    return isinstance(id, list)


class ModelMeta(model.MetaModel):
    def __new__(mcls, name, bases, kws):
        cache = import_string('app.extensions:cache')
        max_find_many_cache = kws.get('__max_find_many_cache__', 10)

        @classmethod
        @cache.cached(
            cache_key=_model_cache_key,
            fallbacked=_find_register,
            unless=_id_is_list, cache_none=True)
        def find(cls, id, columns=None):
            if isinstance(id, list) and id and len(id) <= max_find_many_cache:
                keymap = {i: _model_cache_key(None, cls, i) for i in id}
                rv = cache.get_many(keymap.values())
                models = dict(zip(id, rv))
                missids = [
                    i for i, m in models.items()
                    if m is None]
                models = {
                    k: m for k, m in models.items()
                    if not (m is CacheNone or m is None)}
                if not missids:
                    return cls().new_collection(models.values())
                missed = super(cls, cls).find(missids, columns)
                missed = {m.id: m for m in missed}
                models.update(missed)
                key_model_map = {keymap[i]: m for i, m in missed.items()}
                cache.set_many(key_model_map)
                _bulk_register_to_related_caches(cls, key_model_map)
                return cls().new_collection(list(models.values()))
            return super(cls, cls).find(id, columns)

        @classmethod
        def find_or_fail(cls, id, columns=None):
            result = cls.find(id, columns)
            if isinstance(id, list):
                if len(result) == len(set(id)):
                    return result
            elif result and result is not CacheNone:
                return result

            raise ModelNotFound(cls)

        @classmethod
        @cache.cached(
            cache_key=_model_cache_key,
            fallbacked=_find_by_register, cache_none=True)
        def find_by(cls, name, val, columns=None):
            return cls.where(name, '=', val).first(columns)

        @classmethod
        def find_by_or_fail(cls, name, val, columns=None):
            result = cls.find_by(name, val, columns)

            if result and result is not CacheNone:
                return result

            raise ModelNotFound(cls)

        kws.update({
            'find': find,
            'find_by': find_by,
            'find_or_fail': find_or_fail,
            'find_by_or_fail': find_by_or_fail
        })
        return super().__new__(mcls, name, bases, kws)

    def __init__(cls, name, bases, kws):
        super().__init__(name, bases, kws)
        cls.saved(_clear_related_caches)
        cls.deleted(_clear_related_caches)
