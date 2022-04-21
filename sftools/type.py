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


def SELECT(*args):
    # Note this does NOT support sub-queries in the SELECT
    return JOIN(',', args=chain.from_iterable([a.split(',') for a in args if a]))


def JOIN(separator, left='', right='', args=[]):
    args = [str(arg).strip() for arg in args if arg]
    return separator.join(set([f'{left}{arg}{right}' for arg in args if arg]))


def WHERE_AND(*args):
    return JOIN(' AND ', '(', ')', args)


def WHERE_OR(*args):
    return JOIN(' OR ', '(', ')', args)


def WHERE_IN(name, *args):
    inlist = JOIN(',', "'", "'", args)
    if not inlist:
        return ''
    return f'{name} IN ({inlist})'


def WHERE_LIKE(name, value):
    return f"{name} LIKE '%{value}%'"


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
    def _fields(self):
        return self.describe().get('fields')

    @cached_property
    def _fieldnames(self):
        return tuple([f.get('name') for f in self._fields])

    @cached_property
    def _recordtypeinfos(self):
        return self.describe().get('recordTypeInfos')

    @cached_property
    def _recordtypeids(self):
        '''Note this filters out non-active RecordTypes'''
        return tuple([f.get('recordTypeId') for f in self._recordtypeinfos
                      if f.get('active')])

    @cached_property
    def _where_recordtypeids(self):
        return WHERE_IN(f'{self.name}.RecordTypeId', *self._recordtypeids)

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

    def query(self, where, *, select=None, preload_fields=None, **kwargs):
        '''Query this specific SFType.

        The 'where' parameter should be in standard SOQL format:
        https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_select_conditionexpression.htm

        The 'select' parameter, if provided, must be a string of comma-separated fields.

        If 'preload_fields' is None, it will default to our SF object preload_fields value.

        Returns a QueryResult of matching SFObjects of this SFType.
        '''
        if preload_fields is None:
            preload_fields = self._sf.preload_fields
        select = SELECT(select, 'Id')
        where = WHERE_AND(where, self._where_recordtypeids)
        return self._sf.query(select=select,
                              frm=self.name,
                              where=where,
                              preload_fields=preload_fields,
                              **kwargs)
