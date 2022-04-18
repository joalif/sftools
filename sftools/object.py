#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from contextlib import suppress
from functools import cached_property

try:
    from simple_salesforce import SalesforceMalformedRequest
except ImportError:
    raise RuntimeError('Please install simple-salesforce.')


class SFObject(object):
    '''SF object for object type and object id.'''
    @classmethod
    def getclass(cls, name):
        return globals().get(f'SF{name}Object', SFObject)

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
        return list(set(self._sftype._fieldnames) | set(super().__dir__()))

    def __getattr__(self, attr):
        if attr not in self.__dir__():
            raise AttributeError(f'{self._name} has no attribute {attr}')

        # Is the attribute already in our record?
        if attr in self.record:
            return self.record.get(attr)

        # Perform the dynamic lookup by querying Salesforce
        where = f"{self._name}.Id = '{self.Id}'"
        with suppress(SalesforceMalformedRequest):
            return self._sf.query(select=attr, frm=self._name, where=where).record.get(attr, None)
        return None


class SFCaseObject(SFObject):
    '''SF Case Object.'''
    @cached_property
    def comments(self):
        '''Get all CaseComments for this Case.

        Returns a QueryResult of CaseComment objects.
        '''
        return self._sf.CaseComment.query(where=f"ParentId = '{self.Id}'")


class SFCaseCommentObject(SFObject):
    '''SF CaseComment Object.'''
    def __repr__(self):
        return self.CommentBody

    @cached_property
    def case(self):
        '''Get the Case sfobject for this comment.'''
        return self._sf.Case(self.ParentId)

    def __contains__(self, item):
        '''Check if item in our CommentBody'''
        return item in self.CommentBody
