#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from functools import cached_property
from functools import lru_cache

from sftools.object import SFObject
from sftools.soql import WhereUtil
from sftools.type import SFType


class SFCaseType(SFType, name='Case'):
    '''SF Case Type.'''
    def __call__(self, id_or_number):
        '''Allow looking up cases by Case.Id or Case.CaseNumber'''
        return super().__call__(self._casenumber_to_record(id_or_number))

    def _casenumber_to_record(self, number):
        '''Lookup Case.Id for CaseNumber.

        On failure, 'number' is returned.
        '''
        try:
            n = int(number)
        except (ValueError, TypeError):
            return number

        if len(str(n)) <= 8:
            where = f"CaseNumber = '{str(n).zfill(8)}'"
            return self.query(where=where, only_open=False).record

        return number

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
        return WhereUtil.IN(f'{self.name}.RecordTypeId', *self._recordtypeids)

    def query(self, where, *, only_open=True, only_active_record_type_ids=True, **kwargs):
        '''Case type query.

        This adds parameters to allow restricting query to only open cases,
        as well as only cases with active record type ids. Both default to True.
        '''
        if only_open:
            where = WhereUtil.AND(where, 'IsClosed = FALSE')
        if only_active_record_type_ids:
            where = WhereUtil.AND(where, self._where_recordtypeids)
        return super().query(where, **kwargs)


class SFCaseObject(SFObject, name='Case'):
    '''SF Case Object.'''
    @lru_cache
    def comments(self):
        '''Get all CaseComments for this Case.

        Returns a QueryResult of CaseComment objects.
        '''
        return self._sf.CaseComment.query(where=f"ParentId = '{self.Id}'")
