#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from functools import cached_property

from sftools.case import SFCaseObject
from sftools.object import SFObject
from sftools.type import SFType


# Extend SFCaseObject with timecards()
SFCaseObject.timecards = lambda self: self._sf.sftype('TimeCard__c').fromcase(self)


class SFTimeCardType(SFType, name='TimeCard__c'):
    '''SF TimeCard Type.'''
    def fromcase(self, case):
        return self.query(f"CaseId__c = '{case.Id}'")


class SFTimeCardObject(SFObject, name='TimeCard__c'):
    '''SF TimeCard Object.'''
    pass
