import inspect
import os.path

from sea.config import Config, ConfigAttribute
from sea.datatypes import ImmutableDict


class Sea:
    config_class = Config
    debug = ConfigAttribute('DEBUG')
    testing = ConfigAttribute('TESTING')
    default_config = ImmutableDict({
        'DEBUG': False,
        'TESTING': False
    })

    def __init__(self, root_path, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not os.path.isabs(root_path):
            root_path = os.path.abspath(root_path)
        self.root_path = root_path
        self.config = self.config_class(root_path, self.default_config)
        self.servicers = {}
        self.extensions = {}

    def register_servicer(self, servicer):
        name = servicer.__name__
        if name in self.servicers:
            raise RuntimeError('servicer duplicated: {}'.format(name))
        add_func = self._get_servicer_add_func(servicer)
        self.servicers[name] = (add_func, servicer)

    def _get_servicer_add_func(self, servicer):
        for b in servicer.__bases__:
            if b.__name__ == servicer.__name__:
                m = inspect.getmodule(b)
                return getattr(m, 'add_{}_to_server'.format(b.__name__))
