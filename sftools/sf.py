#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

import re

from copy import copy
from functools import cached_property
from functools import lru_cache

try:
    from simple_salesforce import Salesforce
    from simple_salesforce import SalesforceExpiredSession
except ImportError:
    raise RuntimeError('Please install simple-salesforce.')

from sftools.result import QueryResult
from sftools.result import SearchResult
from sftools.config import SFConfig
from sftools.oauth import SFOAuth
from sftools.soql import SOQL
from sftools.type import SFType


class SF(object):
    '''Interface to Salesforce.

    This is primarily a convenience interface to perform query() and search() calls.

    https://github.com/simple-salesforce/simple-salesforce/blob/master/docs/user_guide/queries.rst
    '''
    # https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_sosl_find.htm#reserved_chars
    SOSL_RESERVED_CHARS = re.compile(r'([?&|!{}[\]()^~*:\\"\'+-])')

    def __init__(self, config=None, verbose=False, preload_fields=False, sf_version=None):
        if isinstance(config, str):
            config = SFConfig(config)
        self._config = config or SFConfig.DEFAULT()
        self._sf_version = sf_version or '53.0'
        self.verbose = verbose
        self.preload_fields = preload_fields

    @property
    def config(self):
        return self._config

    @cached_property
    def oauth(self):
        return SFOAuth(self.config)

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
        # NOTE: Salesforce python lib login function calls the access token the 'session_id'
        if not params.get('session_id'):
            raise RuntimeError('No login configuration found.')
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
        self.config.save()

    def _sf_call_and_refresh(self, func, after_refresh=None):
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
        return self._sf_call_and_refresh(lambda: getattr(self._salesforce, func)(*args, **kwargs))

    def _salesforce_attr(self, attr):
        return self._sf_call_and_refresh(lambda: getattr(self._salesforce, attr))

    @lru_cache
    def sftype(self, typename):
        return SFType.getclass(typename)(self, self._salesforce_attr(typename))

    @cached_property
    def _salesforce_objectnames(self):
        '''Get a list of all valid Salesforce object names.

        This returns names for objects that are:
        - queryable
        - searchable
        '''
        valid = filter(lambda o: o.get('queryable') and o.get('searchable'),
                       self._salesforce_call('describe').get('sobjects'))
        return tuple(map(lambda o: o.get('name'), valid))

    def __dir__(self):
        return tuple(set(self._salesforce_objectnames) |
                     set(dir(self._salesforce)) |
                     set(super().__dir__()))

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
        if self.verbose:
            print(f'SF evaluate: {e}')
        return eval(e, dict(sf=self, **globals()))

    def soql(self, WHERE, **kwargs):
        if not kwargs.get('SELECT') or not kwargs.get('FROM'):
            l = WHERE.split()[0]
            FROM, SELECT = l.split('.')
            kwargs.setdefault('FROM', FROM)
            kwargs.setdefault('SELECT', SELECT)
        kwargs.setdefault('preload_fields', self.preload_fields)
        return SOQL(WHERE=WHERE, **kwargs)

    def _query(self, soql):
        '''Low-level SF query (SOQL)

        You should know what you're doing when you call this.
        '''
        return QueryResult(self.sftype(soql.FROM), self._salesforce_call('query', soql.clause))

    def query_count(self, soql):
        '''SF query (SOQL) count.

        This returns the number of results; this does not return the actual results.
        '''
        soql = copy(soql)
        soql.SELECT = 'COUNT()'
        del soql.ORDER_BY
        return self._query(soql).totalSize

    def query(self, soql_or_where):
        '''SF query (SOQL)

        REST api:
        https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_query.htm
        https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_query.htm

        SOAP api; note this has some more detail but this is not what we use:
        https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/sforce_api_calls_query.htm

        The 'soql' param can be either a SOQL object or WHERE field.

        Returns a QueryResult object.
        '''
        if isinstance(soql_or_where, str):
            soql = self.soql(soql_or_where)
        else:
            soql = copy(soql_or_where)

        # Find out how many records we're going to get
        count = self.query_count(soql)

        # query() has a hard limit of 2000
        hard_limit = 2000

        if soql.preload_fields is None:
            soql.preload_fields = self.preload_fields
        if soql.preload_fields is True:
            soql.SELECT = 'FIELDS(ALL)'
            # FIELDS(ALL) selection has a hard limit of 200
            hard_limit = 200

        if soql.LIMIT:
            count = min(soql.LIMIT, count)
            hard_limit = min(soql.LIMIT, hard_limit)

        # OFFSET has a hard limit of 2000, so max we can get is 2000 + hard_limit
        if count > 2000 + hard_limit:
            raise ValueError(f'Query matches too many results ({count})')

        soql.LIMIT = hard_limit

        results = self._query(soql)
        while results.totalSize < count:
            soql.OFFSET = results.totalSize
            results += self._query(soql)
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

        The 'find' value is always enclosed in brackets before pass to Salesforce; the 'find'
        string should not include enclosing brackets.

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
