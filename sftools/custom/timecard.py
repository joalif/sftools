#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

import dateparser

from datetime import datetime
from datetime import timezone
from functools import partialmethod

from sftools.case import SFCaseObject
from sftools.object import SFObject
from sftools.soql import WhereUtil
from sftools.type import SFType
from sftools.user import SFUserObject


SETTINGS_FORCE_UTC = {
    'RETURN_AS_TIMEZONE_AWARE': True,
    'TO_TIMEZONE': 'UTC',
}


def timecards_from(obj, funcname, **kwargs):
    return getattr(obj._sf.sftype('TimeCard__c'), funcname)(obj, **kwargs)


# Extend SFCaseObject with timecards()
SFCaseObject.timecards = partialmethod(timecards_from, 'fromcase')


# Extend SFUserObject with timecards()
SFUserObject.timecards = partialmethod(timecards_from, 'fromuser')


class SFTimeCardType(SFType, name='TimeCard__c'):
    '''SF TimeCard Type.'''
    def fromcase(self, case, **kwargs):
        return self.query(f"CaseId__c = '{case.Id}'", **kwargs)

    def fromuser(self, user, **kwargs):
        return self.query(f"OwnerId__c = '{user.Id}'", **kwargs)

    def parsedatetime(self, value):
        if value:
            if not isinstance(value, datetime):
                value = dateparser.parse(value, settings=SETTINGS_FORCE_UTC)
            if not value.tzinfo:
                value = value.replace(tzinfo=timezone.utc)
        return value

    def query(self, where, *, before=None, after=None, smaller=None, larger=None, **kwargs):
        before = self.parsedatetime(before)
        if before:
            where = WhereUtil.AND(where, f"StartTime__c <= {before.isoformat()}")
        after = self.parsedatetime(after)
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
