#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from contextlib import suppress

try:
    from simple_salesforce import SalesforceMalformedRequest
except ImportError:
    raise RuntimeError('Please install simple-salesforce.')


class SFObject(object):
    '''SF object for object type and object id.'''
    SUBCLASSES = {}

    @classmethod
    def getclass(cls, name):
        return cls.SUBCLASSES.get(name, cls)

    @classmethod
    def __init_subclass__(cls, /, name, **kwargs):
        cls.SUBCLASSES[name] = cls

    def __init__(self, sftype, record):
        '''Constructor for SFObjects.

        Do not call this directly, only SFType should instantiate objects.
        '''
        self._sf = sftype._sf
        self._sftype = sftype
        self._name = sftype.name
        self._record = record

    @property
    def record(self):
        '''Get our Record.

        Note that the only field our Record is guaranteed to contain is
        our Id. The Record should not be used for attribute access, instead
        access attributes directly on our object.
        '''
        return self._record

    @property
    def Id(self):
        return self.record.get('Id')

    def __dir__(self):
        return list(set(self._sftype.fieldnames) | set(super().__dir__()))

    def __getattr__(self, attr):
        if attr not in self.__dir__():
            raise AttributeError(f'{self._name} has no attribute {attr}')

        # Is the attribute already in our record?
        if attr in self.record:
            return self.record.get(attr)

        # Perform the dynamic lookup by querying Salesforce
        with suppress(SalesforceMalformedRequest):
            return self._sftype.query(where=f"{self._name}.Id = '{self.Id}'",
                                      SELECT=attr).record.get(attr, None)
        return None

    def __repr__(self):
        return f'{self._sftype}: {self.Id}'

    def dumpfields(self, fields=None, label=None):
        if not fields:
            fields = self._sftype.fieldnames
        if label is None:
            label = len(fields) != 1
        for f in fields:
            value = getattr(self, f)
            if label:
                print(f'{f}: {value}')
            else:
                print(value)
