#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

from contextlib import suppress

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
                return self._query(f"Alias = '{alias}'").record.get('Id', alias)
        return alias


class SFUserObject(SFObject, name='User'):
    '''SF User Object.'''
    def cases(self, only_open=True, LIMIT=None, **kwargs):
        limit = int(LIMIT or 0)
        cases = []
        for f in self._sf.Case.fields:
            name = f.get('name')
            if 'Owner' in name and f.get('type') == 'reference':
                soql = SOQL(FROM='Case', WHERE=f"{name} = '{self.Id}'", LIMIT=limit, **kwargs)
                soql.SELECT_AND('Id')
                if only_open:
                    soql.WHERE_AND('IsClosed = False')
                cases.extend(self._sf.query(soql))
            if limit and len(cases) >= limit:
                break
        if limit:
            cases = cases[:limit]
        return cases
