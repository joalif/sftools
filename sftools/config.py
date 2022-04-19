#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

import configparser
import os

from functools import cached_property
from io import StringIO
from pathlib import Path


class SFConfig(object):
    '''SF config file.

    This provides defaults for production and sandbox config, which will be
    automatically updated/maintained by the SF class, or this can be used
    with alternate config files.

    By default, all custom config files are readonly; this will refuse to
    update their content. The default production and sandbox are readwrite
    and their content will be updated automatically. To specify a custom
    config file that should be updated, set the readonly parameter to False.

    This class should NOT be used from multiple processes with the same
    config file, as there is no attempt to synchronize reads/writes nor
    will this class notice if another process updates the config file.
    '''
    DEFAULT_PATH = Path('/etc/sftools')
    USER_PATH = Path(os.getenv('XDG_CONFIG_HOME', '~/.config')).expanduser().resolve() / 'sftools'

    DEFAULT_FILENAME = 'default.conf'
    PRODUCTION_FILENAME = 'production.conf'
    SANDBOX_FILENAME = 'sandbox.conf'

    @classmethod
    def _configparser(cls, read=None, nodefault=False):
        default_section = 'NONE' if nodefault else configparser.DEFAULTSECT
        config = configparser.ConfigParser(default_section=default_section)
        if default_section != configparser.DEFAULTSECT:
            config.add_section(configparser.DEFAULTSECT)
        config.add_section('salesforce')
        if read:
            config.read(read)
        return config

    @classmethod
    def IS_PRODUCTION(cls, configfile=None, fallback=True):
        '''Read only our default config and the provided configfile,
        and determine if we are configured as production or not.
        '''
        configfiles = [cls.DEFAULT_PATH / cls.DEFAULT_FILENAME]
        if configfile:
            configfiles.append(cls.USER_PATH / Path(configfile).expanduser())
        config = cls._configparser(read=configfiles)
        return config.getboolean('salesforce', 'production', fallback=fallback)

    @classmethod
    def DEFAULT(cls):
        if cls.IS_PRODUCTION():
            return cls.PRODUCTION()
        else:
            return cls.SANDBOX()

    @classmethod
    def PRODUCTION(cls):
        return cls(cls.PRODUCTION_FILENAME, readonly=False, production=True)

    @classmethod
    def SANDBOX(cls):
        return cls(cls.SANDBOX_FILENAME, readonly=False, production=False)

    def __init__(self, configfile, readonly=True, production=None):
        self._configfile = configfile
        self._readonly = readonly
        if production is None:
            self._production = self.IS_PRODUCTION(self.path)
        else:
            self._production = production

    @cached_property
    def _user_config(self):
        return self._configparser(read=self.path, nodefault=True)

    @cached_property
    def _default_config(self):
        configfiles = [self.DEFAULT_PATH / self.DEFAULT_FILENAME]
        filename = self.PRODUCTION_FILENAME if self._production else self.SANDBOX_FILENAME
        configfiles.append(self.DEFAULT_PATH / filename)
        config = self._configparser(read=configfiles, nodefault=True)
        return config

    @property
    def config(self):
        config = self._configparser()
        config.read_dict(self._default_config)
        config.read_dict(self._user_config)
        return config

    @cached_property
    def path(self):
        return self.USER_PATH / Path(self._configfile).expanduser()

    @property
    def readonly(self):
        return self._readonly

    def _get(self, func, key, fallback=None, required=False):
        value = func('salesforce', key, fallback=fallback)
        if value is None and required:
            raise ValueError(f'Missing required config: {key}')
        return value

    def get(self, key, fallback=None, required=False):
        return self._get(self.config.get, key, fallback=fallback, required=required)

    def getboolean(self, key, fallback=None, required=False):
        return self._get(self.config.getboolean, key, fallback=fallback, required=required)

    def set(self, key, value):
        '''Set the key to value.

        This only changes the in-memory value in our config instance.

        To save this change to our config file, use the save() method.
        '''
        if 'production' not in self._user_config['salesforce']:
            # Store 'production' setting if not yet set
            self._user_config.set('salesforce', 'production', str(self._production))
        self._user_config.set('salesforce', key, value)

    def save(self):
        '''Save our current config to our config file.

        If this is read-only, this will refuse to save to the file,
        and will instead print out our config and ask the user
        to manually update the config file.
        '''
        content = self._repr(full=False)
        if self.readonly:
            print('Refusing to save config to file, please update it manually:')
            print('')
            print(content)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(content)

    def __repr__(self):
        return self._repr(True)

    def _repr(self, full):
        if full:
            config = self._configparser(nodefault=True)
            config.read_dict(self._default_config)
            config.read_dict(self._user_config)
        else:
            config = self._user_config
        with StringIO() as s:
            config.write(s)
            return s.getvalue()

    def show(self, full=False):
        print(self._repr(full=full))
