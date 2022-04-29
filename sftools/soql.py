

class SOQL(object):
    '''SOQL query object.

    SOQL syntax:
    https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_select.htm
    '''
    def __init__(self, *,
                 SELECT=None,
                 FROM=None,
                 WHERE=None,
                 ORDER_BY=None,
                 LIMIT=None,
                 OFFSET=None,
                 preload_fields=None):
        self.SELECT = SELECT
        self.FROM = FROM
        self.WHERE = WHERE
        self.ORDER_BY = ORDER_BY
        self.LIMIT = LIMIT
        self.OFFSET = OFFSET
        self.preload_fields = preload_fields

    def list_from_csv(self, value, default=None):
        if not value:
            return [default] if default else []
        if not isinstance(value, list):
            value = [v.strip() for v in value.split(',')]
        # use a dict instead of set to retain ordering, but remove dups
        return list(dict([(v, None) for v in value if v]).keys())

    @property
    def SELECT(self) -> list:
        return self._SELECT

    @SELECT.setter
    def SELECT(self, value: list):
        self._SELECT = self.list_from_csv(value)

    def SELECT_AND(self, value: list):
        self.SELECT += self.list_from_csv(value)

    @property
    def FROM(self) -> str:
        return self._FROM

    @FROM.setter
    def FROM(self, value: str):
        if value and ',' in value:
            raise ValueError(f'Only support a single object in FROM: {value}')
        self._FROM = value

    @property
    def WHERE(self) -> str:
        return self._WHERE

    @WHERE.setter
    def WHERE(self, value: str):
        '''This should be in standard SOQL format:
        https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_select_conditionexpression.htm
        '''
        self._WHERE = value

    def _WHERE_ARGS(self, *args):
        if self.WHERE not in args:
            args = (self.WHERE, *args)
        return args

    def WHERE_AND(self, *args):
        self.WHERE = WhereUtil.AND(*self._WHERE_ARGS(*args))
        return self.WHERE

    def WHERE_OR(self, *args):
        self.WHERE = WhereUtil.OR(*self._WHERE_ARGS(*args))
        return self.WHERE

    @property
    def ORDER_BY(self) -> list:
        return self._ORDER_BY

    @ORDER_BY.setter
    def ORDER_BY(self, value: list):
        self._ORDER_BY = self.list_from_csv(value, default='Id')

    @ORDER_BY.deleter
    def ORDER_BY(self):
        self._ORDER_BY = []

    def ORDER_BY_AND(self, value: list):
        self.ORDER_BY += self.list_from_csv(value)

    @property
    def LIMIT(self) -> int:
        return self._LIMIT

    @LIMIT.setter
    def LIMIT(self, value: int):
        self._LIMIT = int(value or 0)

    @property
    def OFFSET(self) -> int:
        return self._OFFSET

    @OFFSET.setter
    def OFFSET(self, value: int):
        self._OFFSET = int(value or 0)

    @property
    def clause(self):
        if not self.SELECT:
            raise ValueError('SELECT is required')
        if not self.FROM:
            raise ValueError('FROM is required')

        q = f'SELECT {",".join(self.SELECT)} FROM {self.FROM}'
        if self.WHERE:
            q = f'{q} WHERE {self.WHERE}'
        if self.ORDER_BY:
            q = f'{q} ORDER BY {",".join(self.ORDER_BY)}'
        if self.LIMIT:
            q = f'{q} LIMIT {self.LIMIT}'
        if self.OFFSET:
            q = f'{q} OFFSET {self.OFFSET}'
        return q

    def __repr__(self):
        return self.clause


class WhereUtil(object):
    @classmethod
    def IN(cls, name, *args):
        if not name:
            return None
        inlist = [f"'{a}'" for a in args if a]
        if not inlist:
            return None
        return f'{name} IN ({",".join(inlist)})'

    @classmethod
    def LIKE(cls, name, value):
        if not name:
            return None
        if not value:
            return None
        return f"{name} LIKE '%{value}%'"

    @classmethod
    def JOIN(cls, action, *args):
        return f' {action} '.join([f'({a})' for a in args if a])

    @classmethod
    def AND(cls, *args):
        return cls.JOIN('AND', *args)

    @classmethod
    def OR(cls, *args):
        return cls.JOIN('OR', *args)
