#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from functools import cached_property

from sftools.object import SFObject
from sftools.type import SFType


class SFCaseType(SFType, name='Case'):
    '''SF Case Type.'''
    def __call__(self, id_or_number):
        '''Allow looking up cases by Case.Id or Case.CaseNumber'''
        caseid = self._casenumber_to_caseid(id_or_number)
        return super().__call__(caseid)

    def _casenumber_to_caseid(self, number):
        '''Lookup Case.Id for CaseNumber.

        On failure, 'number' is returned.
        '''
        try:
            n = int(number)
        except (ValueError, TypeError):
            return number

        if len(str(n)) <= 8:
            where = f"CaseNumber = '{str(n).zfill(8)}'"
            return self.query(where=where, only_open=False).record.get('Id', number)

        return number

    def query(self, where, *, only_open=True, **kwargs):
        '''Restrict queries to only open cases.'''
        if only_open:
            where = WHERE_AND(where, 'IsClosed = FALSE')
        return super().query(where, **kwargs)


class SFCaseObject(SFObject, name='Case'):
    '''SF Case Object.'''
    @cached_property
    def comments(self):
        '''Get all CaseComments for this Case.

        Returns a QueryResult of CaseComment objects.
        '''
        return self._sf.CaseComment.query(where=f"ParentId = '{self.Id}'")
