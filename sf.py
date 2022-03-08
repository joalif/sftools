#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

import argparse
import os
import re
import requests
import time

from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from configparser import ConfigParser
from contextlib import suppress
from copy import copy
from datetime import datetime
from datetime import timedelta
from functools import cached_property
from functools import lru_cache
from functools import partial
from io import StringIO
from itertools import chain
from pathlib import Path

try:
    from simple_salesforce import Salesforce
    from simple_salesforce import SalesforceExpiredSession
    from simple_salesforce import SalesforceMalformedRequest
except ImportError:
    raise RuntimeError('Please install simple-salesforce.')


class SF(object):
    '''Interface to Salesforce.

    This is primarily a convenience interface to perform query() and search() calls.

    https://github.com/simple-salesforce/simple-salesforce/blob/master/docs/user_guide/queries.rst
    '''
    # https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_sosl_find.htm#reserved_chars
    SOSL_RESERVED_CHARS = re.compile(r'([?&|!{}[\]()^~*:\\"\'+-])')

    @classmethod
    def SELECT(cls, *args):
        # Note this does NOT support sub-queries in the SELECT
        return cls.JOIN(',', args=chain.from_iterable([a.split(',') for a in args if a]))

    @classmethod
    def JOIN(cls, separator, l='', r='', args=[]):
        args = [str(a).strip() for a in args if a]
        return separator.join(set([f'{l}{a}{r}' for a in args if a]))

    @classmethod
    def WHERE_AND(cls, *args):
        return cls.JOIN(' AND ', '(', ')', args)

    @classmethod
    def WHERE_OR(cls, *args):
        return cls.JOIN(' OR ', '(', ')', args)

    @classmethod
    def WHERE_IN(cls, name, *args):
        inlist = cls.JOIN(',', "'", "'", args)
        if not inlist:
            return ''
        return f'{name} IN ({inlist})'

    @classmethod
    def WHERE_LIKE(cls, name, value):
        return f"{name} LIKE '%{value}%'"

    def __init__(self, config=None, verbose=False, preload_fields=False, sf_version=None):
        if isinstance(config, str):
            config = SFConfig(config)
        self._config = config or SFConfig.PRODUCTION()
        self._sf_version = sf_version or '53.0'
        self.verbose = verbose
        self.preload_fields = preload_fields

    @property
    def config(self):
        return self._config

    @cached_property
    def oauth(self):
        production = self.config.getboolean('production')
        access_token = self.config.get('access_token')
        refresh_token = self.config.get('refresh_token')
        return SFOAuth(production, access_token=access_token, refresh_token=refresh_token)

    @property
    def _salesforce_login_params(self):
        password_login_params = {
            'username': self.config.get('username'),
            'password': self.config.get('password'),
            'security_token': self.config.get('security_token'),
        }
        if all(password_login_params.values()):
            # If password login is configured, ignore OAuth config, if any
            return password_login_params
        params = self.oauth.login_params
        # Note that the Salesforce python lib login function calls the access token the 'session_id'
        if not params.get('session_id'):
            raise RuntimeError(f'No login configuration found.')
        return params

    @cached_property
    def _salesforce(self):
        return Salesforce(version=self._sf_version, **self._salesforce_login_params)

    def request_oauth(self):
        '''Perform OAuth and save the tokens to our config file.

        This will REPLACE the existing config file content, if any,
        unless we are using an alternate config file.
        '''
        self.oauth.request_access_token(self.verbose)
        self.config.set('access_token', self.oauth.access_token)
        self.config.set('refresh_token', self.oauth.refresh_token)
        self.config.save()

    def refresh_oauth(self):
        '''Refresh our OAuth access_token and save the token to our config file.

        This will REPLACE the existing config file content, if any,
        unless we are using an alternate config file.

        This should only be used if we have a valid refresh token.
        '''
        # Remove the cached property so it will fetch a new Salesforce instance
        del self._salesforce

        self.oauth.refresh_access_token()
        self.config.set('access_token', self.oauth.access_token)
        self.config.save()

    def _salesforce_call_with_refresh_oauth(self, func, after_refresh=None):
        '''Perform a SF action, i.e. function call or attribute access.

        This will attempt to refresh an expired access token.

        If the 'after_refresh' param is provided, it should be a callable
        which will be called after refreshing oauth, and before the retry
        of 'func'.
        '''
        try:
            return func()
        except SalesforceExpiredSession as e:
            try:
                self.refresh_oauth()
            except ValueError:
                raise e
            if after_refresh:
                after_refresh()
            return func()

    def _salesforce_call(self, func, *args, **kwargs):
        '''Perform a SF call, e.g. query() or search().

        This will attempt to refresh an expired access token.

        The 'func' must be a string name of an attribute of our salesforce instance.
        If our token has expired, after the refresh 'func' will be looked up on
        the new salesforce instance and called.
        '''
        if self.verbose:
            params = list(args) + [f'{key}={value}' for key, value in kwargs.items()]
            print(f'SF: {func}({", ".join(params)})')
        return self._salesforce_call_with_refresh_oauth(lambda: getattr(self._salesforce, func)(*args, **kwargs))

    def _salesforce_attr(self, attr):
        return self._salesforce_call_with_refresh_oauth(lambda: getattr(self._salesforce, attr))

    @lru_cache
    def sftype(self, typename):
        return SFType.getclass(typename)(self, self._salesforce_attr(typename))

    @cached_property
    def _salesforce_objectnames(self):
        '''Get a list of all valid Salesforce object names.

        This returns names for objects that are:
        - non-custom
        - queryable
        - searchable
        '''
        valid = filter(lambda o: o.get('queryable') and o.get('searchable') and not o.get('custom'),
                       self._salesforce_call('describe').get('sobjects'))
        return tuple(map(lambda o: o.get('name'), valid))

    def __dir__(self):
        return tuple(set(self._salesforce_objectnames) | set(dir(self._salesforce)) | set(super().__dir__()))

    def __getattr__(self, attr):
        if attr in self._salesforce_objectnames:
            return self.sftype(attr)
        if attr in dir(self._salesforce):
            return getattr(self._salesforce, attr)
        raise AttributeError(f"Salesforce has no object type '{attr}'")

    def evaluate(self, e):
        '''Evaluate the given string as a single command to run on our object.

        The string should be in the form of attributes and calls to our object,
        for example "Case(12345).AccountId" which would return the result of
        self.Case(12345).AccountId.
        '''
        # Provide 'sf' in locals, since it's provided in shell mode
        sf = self
        if self.verbose:
            print(f'SF evaluate: {e}')
        eval(e, globals(), locals())

    def _query(self, *, select, frm, where, orderby=None, limit=None, offset=None):
        '''Low-level SF query (SOQL)

        You should know what you're doing when you call this.
        '''
        if ',' in frm:
            raise ValueError(f'Invalid query(), we only support a single object in FROM: from={frm}')

        clause = f'SELECT {select} FROM {frm} WHERE {where}'
        if orderby:
            clause += f' ORDER BY {orderby}'
        if limit:
            clause += f' LIMIT {limit}'
        if offset:
            clause += f' OFFSET {offset}'
        return QueryResult(self.sftype(frm), self._salesforce_call('query', clause))

    def query_count(self, *, frm, where):
        '''SF query (SOQL) count.

        This returns the number of results; this does not return the actual results.
        '''
        return self._query(select='COUNT()', frm=frm, where=where).totalSize

    def query(self, *, select, frm, where, orderby=None, preload_fields=False):
        '''SF query (SOQL)

        REST api:
        https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_query.htm
        https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_query.htm

        SOAP api; note this has some more detail but this is not what we use:
        https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/sforce_api_calls_query.htm

        Note since 'from' is a keyword, the parameter name is 'frm'

        If 'preload_fields' is True, we will select ALL fields and ignore the 'select' parameter.

        Returns a QueryResult object.
        '''
        params = {
            'select': select,
            'frm': frm,
            'where': where,
            'orderby': orderby or 'Id',
        }

        # Find out how many records we're going to get
        count = self.query_count(frm=frm, where=where)

        # query() has a hard limit of 2000
        limit = 2000

        if preload_fields is True:
            params['select'] = 'FIELDS(ALL)'
            # FIELDS(ALL) selection has a hard limit of 200
            limit = 200

        # OFFSET has a hard limit of 2000, so max we can get is 2000 + limit
        if count > 2000 + limit:
            raise ValueError(f'Query matches too many results ({count})')

        params['limit'] = limit

        results = self._query(**params)
        while results.totalSize < count:
            params['offset'] = results.totalSize
            results += self._query(**params)
        return results

    def search(self, find, returning, *, escape_find=True):
        '''SF search (SOSL)

        REST api:
        https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_search.htm
        https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_search.htm

        SOAP api; note this has some more detail but this is not what we use:
        https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/sforce_api_calls_search.htm

        SOSL syntax:
        https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_sosl_syntax.htm

        If 'escape_find' is True (the default), all reserved characters in the string are escaped.

        The 'find' value is always enclosed in brackets before pass to Salesforce; the 'find' string
        should not include enclosing brackets.

        Returns a SearchResult object.
        '''
        raise NotImplementedError('Not Implemented!')
        if escape_find:
            find = self.escape_sosl(find)
        find = '{' + find + '}'
        clause = f'FIND {find} RETURNING {returning}'
        return SearchResult(self.sftype(returning), self._salesforce_call('search', clause))

    def escape_sosl(self, search):
        '''Format a search string into SOSL FIND clause.

        SOSL FIND syntax, including reserved characters:
        https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_sosl_find.htm
        '''
        return self.SOSL_RESERVED_CHARS.sub(r'\\\1', search)


class SFConfig(object):
    '''SF config file.

    This provides defaults for production and sandbox config, which will be
    automatically updated/maintained by the SF class, or this can be used
    with alternate config files.

    By default, all custom config files are readonly; this will refuse to
    update their content. The default production and sandbox are readwrite
    and their content will be updated automatically. To specify a custom
    config file that should be updated, set the readonly parameter to False.

    This class should NOT be used from multiple processes with the same
    config file, as there is no attempt to synchronize reads/writes nor
    will this class notice if another process updates the config file.
    '''
    @classmethod
    def PRODUCTION(cls):
        # NOTE: unfortunately @classmethod can't be used with @property until py3.9
        #       so, this and SANDBOX must be classmethods to be portable to older py
        return cls(cls.configdir() / 'production.conf', readonly=False, production=True)

    @classmethod
    def SANDBOX(cls):
        return cls(cls.configdir() / 'sandbox.conf', readonly=False, production=False)

    @classmethod
    def configdir(cls):
        xdg_config_home = os.getenv('XDG_CONFIG_HOME', '~/.config')
        return Path(xdg_config_home).expanduser().resolve() / 'sftool'

    def __init__(self, configfile, readonly=True, production=True):
        self._configfile = configfile
        self._readonly = readonly
        self._config_defaults = {'production': production}

    @cached_property
    def config(self):
        config = ConfigParser(defaults=self._config_defaults)
        config.add_section('salesforce')
        config.read(self.path)
        return config

    def __repr__(self):
        with StringIO() as s:
            self.config.write(s)
            return s.getvalue()

    @cached_property
    def path(self):
        return Path(self._configfile).expanduser().resolve()

    @property
    def readonly(self):
        return self._readonly

    def get(self, key, fallback=None):
        return self.config.get('salesforce', key, fallback=fallback)

    def getboolean(self, key, fallback=None):
        return self.config.getboolean('salesforce', key, fallback=fallback)

    def set(self, key, value):
        '''Set the key to value.

        This only changes the in-memory value in our config instance.

        To save this change to our config file, use the save() method.
        '''
        self.config.set('salesforce', key, value)

    def save(self):
        '''Save our current config to our config file.

        If this is read-only, this will refuse to save to the file,
        and will instead print out our config and ask the user
        to manually update the config file.
        '''
        if self.readonly:
            print('Refusing to save config to file, please update it manually:')
            print('')
            print(str(self))
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(self))

    def show(self):
        print(self)


class SFType(object):
    '''SF type.

    This extends the simple salesforce SFType to make the type directly callable.
    '''
    @classmethod
    def getclass(cls, name):
        return globals().get(f'SF{name}Type', SFType)

    def __init__(self, sf, sftype):
        '''Constructor for SFTypes.

        Do not call this directly, only SF should instantiate types.
        '''
        self._sf = sf
        self._sftype = sftype
        self._sfobjects = {}

        # We have to wrap the simple salesforce SFType._call_salesforce() method
        # so we can catch and handle expired sessions
        def wrapper(func, *args, **kwargs):
            p = partial(func, *args, **kwargs)
            try:
                return p()
            except SalesforceExpiredSession as e:
                try:
                    self._sf.refresh_oauth()
                    self._sftype.session_id = self._sf.session_id
                except ValueError:
                    raise e
                return p()
        self._sftype._call_salesforce = partial(wrapper, self._sftype._call_salesforce)

    @cached_property
    def _fields(self):
        return self.describe().get('fields')

    @cached_property
    def _fieldnames(self):
        return tuple([f.get('name') for f in self._fields])

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
        return SF.WHERE_IN(f'{self.name}.RecordTypeId', *self._recordtypeids)

    def __getattr__(self, attr):
        if attr.startswith('_'):
            raise AttributeError(f'{self.name} has no attribute {attr}')
        return getattr(self._sftype, attr)

    def __dir__(self):
        return list(set(dir(self._sftype)) | set(super().__dir__()))

    def _record_to_sfobject(self, record):
        objid = record.get('Id')
        if objid in self._sfobjects:
            obj = self._sfobjects.get(objid)
            obj.record.update(record)
        else:
            obj = SFObject.getclass(self.name)(self, record)
            self._sfobjects[objid] = obj
        return obj

    def __call__(self, id_or_record):
        if not id_or_record:
            return None

        if isinstance(id_or_record, Record):
            return self._record_to_sfobject(id_or_record)

        if id_or_record in self._sfobjects:
            return self._sfobjects.get(id_or_record)

        with suppress(SalesforceMalformedRequest):
            return self._query(where=f"Id = '{id_or_record}'").sfobject
        return None

    def _query(self, where, *, select=None, preload_fields=None):
        if preload_fields is None:
            preload_fields = self._sf.preload_fields
        select = SF.SELECT(select, 'Id')
        where = SF.WHERE_AND(where, self._where_recordtypeids)
        return self._sf.query(select=select, frm=self.name, where=where, preload_fields=preload_fields)

    def query(self, where, *, select=None, preload_fields=None):
        '''Query this specific SFType.

        The 'where' parameter should be in standard SOQL format:
        https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_select_conditionexpression.htm

        The 'select' parameter, if provided, must be a string of comma-separated fields.

        If 'preload_fields' is None, it will default to our SF object preload_fields value.

        Returns a QueryResult of matching SFObjects of this SFType.
        '''
        return self._query(where, select=select, preload_fields=preload_fields)


class SFCaseType(SFType):
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
            where = SF.WHERE_AND(where, 'IsClosed = FALSE')
        return super().query(where, **kwargs)


class SFCaseCommentType(SFType):
    '''SF Case Type.'''
    def contains(self, searchstring):
        '''Search all CaseComments for the searchstring.

        returns a QueryResult of matching CaseComment objects.
        '''
        return self.query(SF.WHERE_LIKE('CommentBody', searchstring))


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
        return list(filter(None, (set(self._sftype._fieldnames) |
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


class OAuthPending(Exception):
    pass


class OAuthSlowDown(OAuthPending):
    pass


class OAuthFailed(Exception):
    pass


class SFOAuth(object):
    '''Salesforce OAuth.

    We use the Device Flow.
    https://www.oauth.com/oauth2-servers/device-flow/authorization-request/

    If you have a access and refresh token, set those on this instance either
    when the instance is created or after. Then you can read the access token,
    and if/when it expires, you can call refresh_access_token() to refresh it.

    To create new access and refresh tokens, call the request_access_token()
    method, which will interactively perform OAuth and update the access and
    refresh tokens.
    '''
    PRODUCTION_CLIENT_ID = '3MVG9WtWSKUDG.x4DRiupfwgvo8QIUtDtf9GkzuGiGN_YJlFmGEvF9E3OtcrLNDVx21_EUQC_nafPFePs._0l'
    PRODUCTION_INSTANCE = 'canonical.my.salesforce.com'
    PRODUCTION_DOMAIN = 'login'

    SANDBOX_CLIENT_ID = '3MVG9rKhT8ocoxGkPdSEUBFzU_WubXBhhzjwCCg3pOMYzbt6.FngYpJWSfgfKS9C67kKo5a8KpW.vKDbtVAQ_'
    SANDBOX_INSTANCE = 'canonical--obiwan.my.salesforce.com'
    SANDBOX_DOMAIN = 'test'

    def __init__(self, production=True, access_token=None, refresh_token=None):
        self.production = production
        self.access_token = access_token
        self.refresh_token = refresh_token

    @property
    def client_id(self):
        return self.PRODUCTION_CLIENT_ID if self.production else self.SANDBOX_CLIENT_ID

    @property
    def instance(self):
        return self.PRODUCTION_INSTANCE if self.production else self.SANDBOX_INSTANCE

    @property
    def instance_url(self):
        return f'https://{self.instance}'

    @property
    def token_url(self):
        return f'{self.instance_url}/services/oauth2/token'

    @property
    def domain(self):
        return self.PRODUCTION_DOMAIN if self.production else self.SANDBOX_DOMAIN

    @property
    def login_params(self):
        return {
            'instance': self.instance,
            'domain': self.domain,
            'session_id': self.access_token,
        }

    def _post(self, data):
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        return requests.post(self.token_url, data=data, headers=headers)

    def request_access_token(self, show_token=False):
        verification = self._request_verification_code()
        print(f"Please approve access: {verification.url}")
        print('Waiting for verification...', end='', flush=True)

        start = datetime.now()
        timeout = timedelta(minutes=5)
        interval = int(verification.interval or 1)
        code = verification.device_code
        while datetime.now() - start < timeout:
            try:
                token = self._request_access_token(code)
                self.access_token = token.get('access_token')
                self.refresh_token = token.get('refresh_token')
                print('approved.')
                print('')
                if show_token:
                    print(token)
                return
            except OAuthSlowDown:
                interval += 1
            except OAuthPending:
                pass

            time.sleep(interval)
            print('.', end='', flush=True)

        print('Verification timeout.')

    def _request_verification_code(self):
        r = self._post({
            'response_type': 'device_code',
            'scope': 'full refresh_token',
            'client_id': self.client_id,
        })

        r.raise_for_status()
        return SFOAuthVerification(r.json())

    def _request_access_token(self, device_code):
        r = self._post({
            'grant_type': 'device',
            'client_id': self.client_id,
            'code': device_code,
        })

        response = r.json()

        if r.status_code == 200:
            return response

        if r.status_code == 400:
            e = response.get('error')
            if e == 'authorization_pending':
                raise OAuthPending()
            if e == 'slow_down':
                raise OAuthSlowDown()

            d = response.get('error_description')
            if e in ['server_error', 'invalid_request']:
                msg = f'Error waiting for authorization: {d}'
            elif e == 'invalid_grant':
                msg = f'Invalid grant for this app (internal error): {d}'
            elif e == 'access_denied':
                msg = f'User denied access: {d}'
            else:
                msg = f'Unknown error: {e} ({d})'
            raise OAuthFailed(msg)

        raise OAuthFailed(f'Unexpected response status: {response.status_code}')

    def refresh_access_token(self):
        '''Refresh the access token.

        https://www.oauth.com/oauth2-servers/making-authenticated-requests/refreshing-an-access-token/
        '''
        if not self.refresh_token:
            raise ValueError('Must set refresh_token before refreshing access token.')

        r = self._post({
            'grant_type': 'refresh_token',
            'client_id': self.client_id,
            'refresh_token': self.refresh_token,
        })

        r.raise_for_status()
        self.access_token = r.json().get('access_token')
        self.access_token


class SFOAuthVerification(object):
    def __init__(self, response):
        self.verification_uri = response.get('verification_uri')
        self.interval = response.get('interval')
        self.user_code = response.get('user_code')
        self.device_code = response.get('device_code')
        params = {'user_code': self.user_code}
        self.url = requests.Request('GET', self.verification_uri, params=params).prepare().url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Be verbose.')
    lazy = parser.add_mutually_exclusive_group()
    lazy.add_argument('--lazy-fields', action='store_true',
                      help='Load object fields lazily (default, except in shell mode)')
    lazy.add_argument('--preload-fields', action='store_true',
                      help='Preload all object fields (default only in shell mode)')
    config = parser.add_mutually_exclusive_group()
    config.add_argument('-c', '--config',
                        help='Alternate config file to use')
    config.add_argument('-P', '--production', action='store_true',
                        help='Use standard production server config file (default)')
    config.add_argument('-S', '--sandbox', action='store_true',
                        help='Use sandbox server config file')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--show-config', action='store_true',
                        help='Show current config')
    action.add_argument('-s', '--shell', action='store_true',
                        help='Start interactive shell')
    action.add_argument('-o', '--oauth', action='store_true',
                        help='Request new OAuth token')
    action.add_argument('--oauth-refresh', action='store_true',
                        help='Refresh existing OAuth token')
    action.add_argument('-e', '--evaluate',
                        help='Evaluate and print result (e.g. "-e sf.Case(123456).AccountId")')

    opts = parser.parse_args()

    preload_fields = opts.shell
    if opts.lazy_fields:
        preload_fields = False
    elif opts.preload_fields:
        preload_fields = True

    config = None
    if opts.config:
        config = SFConfig(opts.config)
    elif opts.sandbox:
        config = SFConfig.SANDBOX()

    sf = SF(config, verbose=opts.verbose, preload_fields=preload_fields)
    if opts.show_config:
        sf.config.show()
    elif opts.oauth:
        sf.request_oauth()
    elif opts.oauth_refresh:
        sf.refresh_oauth()
    elif opts.evaluate:
        sf.evaluate(opts.evaluate)
    else:
        try:
            import IPython
            IPython.start_ipython(argv=[], user_ns={'sf': sf})
        except ImportError:
            print('Please install ipython.')


if __name__ == "__main__":
    main()
