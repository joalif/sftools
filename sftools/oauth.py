#!/usr/bin/python3
#
# Copyright 2022 Dan Streetman <ddstreet@ieee.org>

import requests
import time

from configparser import ConfigParser
from datetime import datetime
from datetime import timedelta


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

    To create new access and refresh tokens, call the request_access_token()
    method, which will interactively perform OAuth and update the access and
    refresh tokens.
    '''
    def __init__(self, config):
        self.config = config

    @property
    def access_token(self):
        return self.config.get('access_token')

    @access_token.setter
    def access_token(self, value):
        self.config.set('access_token', value)

    @property
    def refresh_token(self):
        return self.config.get('refresh_token')

    @refresh_token.setter
    def refresh_token(self, value):
        self.config.set('refresh_token', value)

    @property
    def client_id(self):
        return self.config.get('client_id', required=True)

    @property
    def instance(self):
        return self.config.get('instance', required=True)

    @property
    def domain(self):
        return self.config.get('domain', required=True)

    @property
    def instance_url(self):
        return f'https://{self.instance}'

    @property
    def token_url(self):
        return f'{self.instance_url}/services/oauth2/token'

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


class SFOAuthVerification(object):
    def __init__(self, response):
        self.verification_uri = response.get('verification_uri')
        self.interval = response.get('interval')
        self.user_code = response.get('user_code')
        self.device_code = response.get('device_code')
        params = {'user_code': self.user_code}
        self.url = requests.Request('GET', self.verification_uri, params=params).prepare().url
