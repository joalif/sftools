#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from functools import partial

from sftools.case import SFCaseObject
from sftools.object import SFObject
from sftools.soql import WhereUtil
from sftools.type import SFType
from sftools.user import SFUserObject


def timecards_from(funcname, obj, **kwargs):
    return getattr(obj._sf.sftype('TimeCard__c'), 'funcname')(obj, **kwargs)


# Extend SFCaseObject with timecards()
SFCaseObject.timecards = partial(timecards_from, 'fromcase')


# Extend SFUserObject with timecards()
SFUserObject.timecards = partial(timecards_from, 'fromuser')


class SFTimeCardType(SFType, name='TimeCard__c'):
    '''SF TimeCard Type.'''
    def fromcase(self, case, **kwargs):
        return self.query(f"CaseId__c = '{case.Id}'", **kwargs)

    def fromuser(self, user, **kwargs):
        return self.query(f"OwnerId__c = '{user.Id}'", **kwargs)

    def query(self, where, *, before=None, after=None, smaller=None, larger=None, **kwargs):
        if before:
            where = WhereUtil.AND(where, f"EndTime__c <= {before.isoformat()}")
        if after:
            where = WhereUtil.AND(where, f"StartTime__c >= {after.isoformat()}")
        if larger:
            where = WhereUtil.AND(where, f"TotalMinutesStatic__c >= {larger}")
        if smaller:
            where = WhereUtil.AND(where, f"TotalMinutesStatic__c <= {smaller}")
        return super().query(where, **kwargs)


class SFTimeCardObject(SFObject, name='TimeCard__c'):
    '''SF TimeCard Object.'''
    pass
