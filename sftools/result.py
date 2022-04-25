#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from copy import copy

from sftools.object import SFObject


class Result(Sequence, ABC):
    '''Result of query() or search().'''
    def __init__(self, sftype, result):
        super().__init__()
        self._sftype = sftype
        self._result = result

    @property
    def records(self):
        return tuple([Record(r) for r in self._records])

    @property
    def sfobjects(self):
        return tuple([self._sftype(r) for r in self.records])

    @property
    def record(self):
        '''Get our first Record, or an empty Record if we have no Records.

        It is always safe to call get() on the return value.
        '''
        try:
            return list(self.records)[0]
        except IndexError:
            return Record()

    @property
    def sfobject(self):
        '''Get our first SFObject, or None if we have no Records.'''
        try:
            return list(self.sfobjects)[0]
        except IndexError:
            return None

    @property
    @abstractmethod
    def _records(self):
        pass

    def __getattr__(self, attr):
        if attr not in self.__dir__():
            raise AttributeError(f'{self._sftype.name} has no attribute {attr}')

        return list(filter(None, set([getattr(o, attr, None) for o in self.sfobjects])))

    def __dir__(self):
        return list(filter(None, (set(self._sftype.fieldnames) |
                                  set(super().__dir__()) |
                                  set(dir(SFObject.getclass(self._sftype.name))))))

    def __getitem__(self, key):
        return list(self.sfobjects)[key]

    def __iter__(self):
        yield from self.sfobjects

    def __len__(self):
        return len(self.records)


class Record(dict):
    '''Record.

    This matches a record as returned inside a query() or search() result.

    Besides its 'attributes' attribute, records are just a dictionary with
    query-specific content.

    This overrides getattr so all dictionary keys can be directly accessed
    as attributes.
    '''
    @property
    def attributes(self):
        '''Get the RecordAttributes.

        If we have none (if we are an empty Record), this returns an
        empty RecordAttributes object.
        '''
        a = self.get('attributes')
        if a:
            return RecordAttributes(a)
        return RecordAttributes()


class RecordAttributes(dict):
    @property
    def type(self):
        return self.get('type')

    @property
    def url(self):
        return self.get('url')


class QueryResult(Result):
    '''QueryResult.

    REST api:
    https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_query.htm

    SOAP api result; note this is not what we use here:
    https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/sforce_api_calls_query_queryresult.htm
    '''
    @property
    def done(self):
        return self._result.get('done', True)

    @property
    def _records(self):
        return self._result.get('records', [])

    @property
    def totalSize(self):
        '''Online docs name this field "size", but in actual result field name is "totalSize"'''
        return int(self._result.get('totalSize', 0))

    def __add__(self, other):
        result = copy(other._result)
        result['done'] = self.done or other.done
        result['totalSize'] = self.totalSize + other.totalSize
        result['records'] = ((self._result.get('records', [])) +
                             (other._result.get('records', [])))
        return self.__class__(self._sftype, result)


class SearchResult(Result):
    '''SearchResult.

    REST api:
    https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_search.htm

    SOAP api result; note this is not what we use here:
    https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/sforce_api_calls_search_searchresult.htm
    '''
    @property
    def _records(self):
        return self.searchRecords

    @property
    def searchRecords(self):
        return self._result.get('searchRecords', [])

    def __add__(self, other):
        result = copy(other._result)
        result['searchRecords'] = ((self._result.get('searchRecords', [])) +
                                   (other._result.get('searchRecords', [])))
        return self.__class__(self._sftype, result)
