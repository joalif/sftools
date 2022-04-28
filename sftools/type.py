#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from contextlib import suppress
from functools import cached_property
from functools import partial
from itertools import chain

try:
    from simple_salesforce import SalesforceExpiredSession
    from simple_salesforce import SalesforceMalformedRequest
except ImportError:
    raise RuntimeError('Please install simple-salesforce.')

from sftools.object import SFObject
from sftools.result import Record
from sftools.soql import SOQL


class SFType(object):
    '''SF type.

    This extends the simple salesforce SFType to make the type directly callable.
    '''
    SUBCLASSES = {}

    @classmethod
    def getclass(cls, name):
        return cls.SUBCLASSES.get(name, cls)

    @classmethod
    def __init_subclass__(cls, /, name, **kwargs):
        cls.SUBCLASSES[name] = cls

    def __init__(self, sf, sftype):
        '''Constructor for SFTypes.

        Do not call this directly, only SF should instantiate types.
        '''
        self._sf = sf
        self._sftype = sftype
        self._sfobjects = {}

        # We have to wrap the simple salesforce SFType._call_salesforce() method
        # so we can catch and handle expired sessions
        def wrapper(func, *args, **kwargs):
            p = partial(func, *args, **kwargs)
            try:
                return p()
            except SalesforceExpiredSession as e:
                try:
                    self._sf.refresh_oauth()
                    self._sftype.session_id = self._sf.session_id
                except ValueError:
                    raise e
                return p()
        self._sftype._call_salesforce = partial(wrapper, self._sftype._call_salesforce)

    @cached_property
    def fields(self):
        return self.describe().get('fields')

    @cached_property
    def fieldnames(self):
        return tuple([f.get('name') for f in self.fields])

    def __getattr__(self, attr):
        if attr.startswith('_'):
            raise AttributeError(f'{self.name} has no attribute {attr}')
        return getattr(self._sftype, attr)

    def __repr__(self):
        return self._sftype.name

    def __dir__(self):
        return list(set(dir(self._sftype)) | set(super().__dir__()))

    def _record_to_sfobject(self, record):
        objid = record.get('Id')
        if objid in self._sfobjects:
            obj = self._sfobjects.get(objid)
            obj.record.update(record)
        else:
            obj = SFObject.getclass(self.name)(self, record)
            self._sfobjects[objid] = obj
        return obj

    def __call__(self, id_or_record):
        if not id_or_record:
            return None

        if isinstance(id_or_record, Record):
            return self._record_to_sfobject(id_or_record)

        if id_or_record in self._sfobjects:
            return self._sfobjects.get(id_or_record)

        with suppress(SalesforceMalformedRequest):
            return self.query(where=f"Id = '{id_or_record}'").sfobject
        return None

    def query(self, where, **kwargs):
        '''Query this specific SFType.

        The 'where' parameter should be in standard SOQL format:
        https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_select_conditionexpression.htm

        Returns a QueryResult of matching SFObjects of this SFType.
        '''
        soql = SOQL(FROM=self.name, WHERE=where, **kwargs)
        soql.SELECT_AND('Id')
        return self._sf.query(soql)
