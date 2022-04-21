#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from functools import cached_property

from sftools.object import SFObject
from sftools.type import SFType


class SFCaseCommentType(SFType, name='CaseComment'):
    '''SF Case Type.'''
    def contains(self, searchstring):
        '''Search all CaseComments for the searchstring.

        returns a QueryResult of matching CaseComment objects.
        '''
        return self.query(WHERE_LIKE('CommentBody', searchstring))


class SFCaseCommentObject(SFObject, name='CaseComment'):
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
