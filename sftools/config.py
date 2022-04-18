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
    @classmethod
    def PRODUCTION(cls):
        # NOTE: unfortunately @classmethod can't be used with @property until py3.9
        #       so, this and SANDBOX must be classmethods to be portable to older py
        return cls(cls.configdir() / 'production.conf', readonly=False, production=True)

    @classmethod
    def SANDBOX(cls):
        return cls(cls.configdir() / 'sandbox.conf', readonly=False, production=False)

    @classmethod
    def configdir(cls):
        xdg_config_home = os.getenv('XDG_CONFIG_HOME', '~/.config')
        return Path(xdg_config_home).expanduser().resolve() / 'sftool'

    def __init__(self, configfile, readonly=True, production=True):
        self._configfile = configfile
        self._readonly = readonly
        self._config_defaults = {'production': production}

    @cached_property
    def config(self):
        config = ConfigParser(defaults=self._config_defaults)
        config.add_section('salesforce')
        config.read(self.path)
        return config

    def __repr__(self):
        with StringIO() as s:
            self.config.write(s)
            return s.getvalue()

    @cached_property
    def path(self):
        return Path(self._configfile).expanduser().resolve()

    @property
    def readonly(self):
        return self._readonly

    def get(self, key, fallback=None):
        return self.config.get('salesforce', key, fallback=fallback)

    def getboolean(self, key, fallback=None):
        return self.config.getboolean('salesforce', key, fallback=fallback)

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
