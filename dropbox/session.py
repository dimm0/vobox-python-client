"""
dropbox.session.DropboxSession is responsible for holding OAuth authentication info
(app key/secret, request key/secret,  access key/secret) as well as configuration information for your app
('app_folder' or 'dropbox' access type, optional locale preference). It knows how to
use all of this information to craft properly constructed requests to Dropbox.

A DropboxSession object must be passed to a dropbox.client.DropboxClient object upon
initialization.
"""
from __future__ import absolute_import

import random
import sys
import time
import urllib

try:
    from urlparse import parse_qs
except ImportError:
    # fall back for Python 2.5
    from cgi import parse_qs

from . import rest

class OAuthToken(object):
    __slots__ = ('key', 'secret')
    def __init__(self, key, secret):
        self.key = key
        self.secret = secret

class DropboxSession(object):
    API_VERSION = 1

    API_HOST = "www.scidrive.org/vospace-2.0"
    WEB_HOST = "www.scidrive.org/vospace-2.0"
    API_CONTENT_HOST = "www.scidrive.org/vospace-2.0"

    def __init__(self, consumer_key, consumer_secret, access_type, locale=None, rest_client=rest.RESTClient, server='www.scidrive.org/vospace-2.0'):
        """Initialize a DropboxSession object.

        Your consumer key and secret are available
        at https://www.dropbox.com/developers/apps

        Args:
            - ``access_type``: Either 'dropbox' or 'app_folder'. All path-based operations
                will occur relative to either the user's Dropbox root directory
                or your application's app folder.
            - ``locale``: A locale string ('en', 'pt_PT', etc.) [optional]
                The locale setting will be used to translate any user-facing error
                messages that the server generates. At this time Dropbox supports
                'en', 'es', 'fr', 'de', and 'ja', though we will be supporting more
                languages in the future. If you send a language the server doesn't
                support, messages will remain in English. Look for these translated
                messages in rest.ErrorResponse exceptions as e.user_error_msg.
        """
        assert access_type in ['dropbox', 'app_folder'], "expected access_type of 'dropbox' or 'app_folder'"
        self.consumer_creds = OAuthToken(consumer_key, consumer_secret)
        self.token = None
        self.request_token = None
        self.root = 'sandbox' if access_type == 'app_folder' else 'dropbox'
        self.locale = locale
        self.rest_client = rest_client
	
	self.API_HOST = server
	self.WEB_HOST = server
	self.API_CONTENT_HOST = server

    def is_linked(self):
        """Return whether the DropboxSession has an access token attached."""
        return bool(self.token)

    def unlink(self):
        """Remove any attached access token from the DropboxSession."""
        self.token = None

    def set_token(self, access_token, access_token_secret):
        """Attach an access token to the DropboxSession.

        Note that the access 'token' is made up of both a token string
        and a secret string.
        """
        self.token = OAuthToken(access_token, access_token_secret)

    def set_request_token(self, request_token, request_token_secret):
        """Attach an request token to the DropboxSession.

        Note that the request 'token' is made up of both a token string
        and a secret string.
        """
        self.request_token = OAuthToken(request_token, request_token_secret)

    def build_path(self, target, params=None):
        """Build the path component for an API URL.

        This method urlencodes the parameters, adds them
        to the end of the target url, and puts a marker for the API
        version in front.

        Args:
            - ``target``: A target url (e.g. '/files') to build upon.
            - ``params``: A dictionary of parameters (name to value). [optional]

        Returns:
            - The path and parameters components of an API URL.
        """
        if sys.version_info < (3,) and type(target) == unicode:
            target = target.encode("utf8")

        target_path = urllib.quote(target)

        params = params or {}
        params = params.copy()

        if self.locale:
            params['locale'] = self.locale

        ver = str(self.API_VERSION)
        if ("token" in target) or ("authorize" in target):
            ver = ""

        if params:
            return "/%s%s?%s" % (ver, target_path, urllib.urlencode(params))
        else:
            return "/%s%s" % (ver, target_path)

    def build_url(self, host, target, params=None):
        """Build an API URL.

        This method adds scheme and hostname to the path
        returned from build_path.

        Args:
            - ``target``: A target url (e.g. '/files') to build upon.
            - ``params``: A dictionary of parameters (name to value). [optional]

        Returns:
            - The full API URL.
        """
        return "http://%s%s" % (host, self.build_path(target, params))

    def build_authorize_url(self, request_token, oauth_callback=None, share=None):
        """Build a request token authorization URL.

        After obtaining a request token, you'll need to send the user to
        the URL returned from this function so that they can confirm that
        they want to connect their account to your app.

        Args:
            - ``request_token``: A request token from obtain_request_token.
            - ``oauth_callback``: A url to redirect back to with the authorized
              request token.

        Returns:
            - An authorization for the given request token.
        """
        params = {'oauth_token': request_token.key,
                    'provider': 'vao',

                  }

        if share:
            params['share'] = share

        if oauth_callback:
            params['oauth_callback'] = oauth_callback

        return self.build_url(self.WEB_HOST, 'authorize', params)

    def obtain_request_token(self, share=None):
        """Obtain a request token from the Dropbox API.

        This is your first step in the OAuth process.  You call this to get a
        request_token from the Dropbox server that you can then use with
        DropboxSession.build_authorize_url() to get the user to authorize it.
        After it's authorized you use this token with
        DropboxSession.obtain_access_token() to get an access token.

        NOTE:  You should only need to do this once for each user, and then you
        can store the access token for that user for later operations.

        Returns:
            - An dropbox.session.OAuthToken representing the request token Dropbox assigned
              to this app. Also attaches the request token as self.request_token.
        """
        self.token = None # clear any token currently on the request
        url = self.build_url(self.API_HOST, 'request_token')
        headers, params = self.build_access_headers('POST', url)
        if share:
            params['share'] = share

        response = self.rest_client.POST(url, headers=headers, params=params, raw_response=True)
        self.request_token = self._parse_token(response.read())
        return self.request_token

    def obtain_access_token(self, request_token=None):
        """Obtain an access token for a user.

        After you get a request token, and then send the user to the authorize
        URL, you can use the authorized request token with this method to get the
        access token to use for future operations. The access token is stored on
        the session object.

        Args:
            - ``request_token``: A request token from obtain_request_token. [optional]
              The request_token should have been authorized via the
              authorization url from build_authorize_url. If you don't pass
              a request_token, the fallback is self.request_token, which
              will exist if you previously called obtain_request_token on this
              DropboxSession instance.

        Returns:
            - An tuple of (key, secret) representing the access token Dropbox assigned
              to this app and user. Also attaches the access token as self.token.
        """
        request_token = request_token or self.request_token
        assert request_token, "No request_token available on the session. Please pass one."
        url = self.build_url(self.API_HOST, 'access_token')
        headers, params = self.build_access_headers('POST', url, request_token=request_token)

        response = self.rest_client.POST(url, headers=headers, params=params, raw_response=True)
        self.token = self._parse_token(response.read())
        return self.token

    def build_access_headers(self, method, resource_url, params=None, request_token=None):
        """Build OAuth access headers for a future request.

        Args:
            - ``method``: The HTTP method being used (e.g. 'GET' or 'POST').
            - ``resource_url``: The full url the request will be made to.
            - ``params``: A dictionary of parameters to add to what's already on the url.
              Typically, this would consist of POST parameters.

        Returns:
            - A tuple of (header_dict, params) where header_dict is a dictionary
              of header names and values appropriate for passing into dropbox.rest.RESTClient
              and params is a dictionary like the one that was passed in, but augmented with
              oauth-related parameters as appropriate.
        """
        if params is None:
            params = {}
        else:
            params = params.copy()

        oauth_params = {
            'oauth_consumer_key' : self.consumer_creds.key,
            'oauth_timestamp' : self._generate_oauth_timestamp(),
            'oauth_nonce' : self._generate_oauth_nonce(),
            'oauth_version' : self._oauth_version(),
        }

        token = request_token if request_token is not None else self.token

        if token:
            oauth_params['oauth_token'] = token.key

        self._oauth_sign_request(oauth_params, self.consumer_creds, token)

        params.update(oauth_params)

        return {}, params

    @classmethod
    def _oauth_sign_request(cls, params, consumer_pair, token_pair):
        params.update({'oauth_signature_method' : 'PLAINTEXT',
                       'oauth_signature' : ('%s&%s' % (consumer_pair.secret, token_pair.secret)
                                            if token_pair is not None else
                                            '%s&' % (consumer_pair.secret,))})

    @classmethod
    def _generate_oauth_timestamp(cls):
        return int(time.time())

    @classmethod
    def _generate_oauth_nonce(cls, length=8):
        return ''.join([str(random.randint(0, 9)) for i in range(length)])

    @classmethod
    def _oauth_version(cls):
        return '1.0'

    @classmethod
    def _parse_token(cls, s):
        if not s:
            raise ValueError("Invalid parameter string.")

        params = parse_qs(s, keep_blank_values=False)
        if not params:
            raise ValueError("Invalid parameter string: %r" % s)

        try:
            key = params['oauth_token'][0]
        except Exception:
            raise ValueError("'oauth_token' not found in OAuth request.")

        try:
            secret = params['oauth_token_secret'][0]
        except Exception:
            raise ValueError("'oauth_token_secret' not found in "
                             "OAuth request.")

        return OAuthToken(key, secret)
