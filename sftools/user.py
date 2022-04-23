#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from contextlib import suppress
from functools import cached_property

try:
    from simple_salesforce import SalesforceMalformedRequest
except ImportError:
    raise RuntimeError('Please install simple-salesforce.')

from sftools.object import SFObject
from sftools.soql import SOQL
from sftools.type import SFType


class SFUserType(SFType, name='User'):
    '''SF User Type.'''
    def __call__(self, id_or_alias):
        '''Allow looking up users by User.Id or User.Alias'''
        userid = self._useralias_to_userid(id_or_alias)
        return super().__call__(userid)

    def _useralias_to_userid(self, alias):
        '''Lookup User.Id for Alias.

        On failure, 'alias' is returned.
        '''
        if isinstance(alias, str):
            with suppress(SalesforceMalformedRequest):
                return self.query(f"Alias = '{alias}'").record.get('Id', alias)
        return alias


class SFUserObject(SFObject, name='User'):
    '''SF User Object.'''
    def cases(self, only_open=True):
        cases = []
        for f in self._sf.Case._fields:
            name = f.get('name')
            if 'Owner' in name and f.get('type') == 'reference':
                soql = SOQL(SELECT='Id', FROM='Case', WHERE=f"{name} = '{self.Id}'")
                if only_open:
                    soql.WHERE_AND('IsClosed = False')
                cases.extend(self._sf.query(soql).Id)
        return [self._sf.Case(Id) for Id in cases]
