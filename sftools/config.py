#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

import os

from configparser import ConfigParser
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
    USER_PATH = Path(os.getenv('XDG_CONFIG_HOME', '~/.config')).expanduser().resolve() / 'sftool'

    DEFAULT_FILENAME = 'default.conf'
    PRODUCTION_FILENAME = 'production.conf'
    SANDBOX_FILENAME = 'sandbox.conf'

    @classmethod
    def IS_PRODUCTION(cls, configfile=None, defaults={}, fallback=True):
        '''Read only our default config and the provided configfile,
        and determine if we are configured as production or not.'''
        config = ConfigParser(defaults=defaults)
        config.add_section('salesforce')
        config.read(cls.DEFAULT_PATH / cls.DEFAULT_FILENAME)
        if configfile:
            config.read(cls.USER_PATH / Path(configfile).expanduser())
        return configparser.getboolean('salesforce', 'production', fallback=fallback)

    @classmethod
    def DEFAULT(cls):
        if cls.IS_PRODUCTION():
            return cls.PRODUCTION()
        else:
            return cls.SANDBOX()

    @classmethod
    def PRODUCTION(cls):
        return cls(cls.PRODUCTION_FILENAME, readonly=False, defaults={'production': 'true'})

    @classmethod
    def SANDBOX(cls):
        return cls(cls.SANDBOX_FILENAME, readonly=False, defaults={'production': 'false'})

    def __init__(self, configfile, readonly=True, defaults={}):
        self._configfile = configfile
        self._readonly = readonly
        self._defaults = defaults

    @cached_property
    def config(self):
        config = ConfigParser(defaults=self._defaults)
        config.add_section('salesforce')
        if self.IS_PRODUCTION(self.path, defaults=self._defaults):
            filename = self.PRODUCTION_FILENAME
        else:
            filename = self.SANDBOX_FILENAME
        config.read([self.DEFAULT_PATH / self.DEFAULT_FILENAME,
                     self.DEFAULT_PATH / filename,
                     self.path])
        return config

    def __repr__(self):
        with StringIO() as s:
            self.config.write(s)
            return s.getvalue()

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
        self.config.set('salesforce', key, value)

    def save(self):
        '''Save our current config to our config file.

        If this is read-only, this will refuse to save to the file,
        and will instead print out our config and ask the user
        to manually update the config file.
        '''
        if self.readonly:
            print('Refusing to save config to file, please update it manually:')
            print('')
            print(str(self))
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(self))

    def show(self):
        print(self)
