"""Client library for logging into reddit and doing things with the API.

(currently only supports flair)

Example:

>>> import redditclient
>>> client = redditclient.RedditClient()
>>> client.log_in()
reddit username: intortus
reddit password: 
True
>>> client.flair('test', 'intortus', 'hi', '')
>>> list(client.flair_list('test'))
[(u'intortus', u'hi', '')]

"""

import cookielib
from cStringIO import StringIO
import csv
import getpass
import json
import logging
import urllib
import urllib2

class RedditClient:
    """A reddit session, with tools for making API calls.
       
    Attrs:
      logged_in: bool, we have a reddit_session cookie
    """

    def __init__(self, host='http://www.reddit.com', cookie_file=None,
            user_agent=None, _http_user=None, _http_password=None):
        """Constructor.

        Args:
          host: str, base URL of reddit site (default: http://www.reddit.com)
          cookie_file: str, optional path to file to save session cookie in
        """
        while host.endswith('/'):
            host = host[:-1]
        self.host = host
        self.user_agent = user_agent
        self.modhash = None

        # set up HTTP digest authentication (for our staging environment, not
        # generally useful)
        self.password_manager = urllib2.HTTPPasswordMgrWithDefaultRealm()
        if _http_user:
            self.password_manager.add_password(None, self.host,
                                               _http_user, _http_password)
        self.auth_handler = urllib2.HTTPDigestAuthHandler(self.password_manager)

        # set up cookie jar, with optional file storage
        if cookie_file:
            self.cookies = cookielib.LWPCookieJar(cookie_file)
            try:
                self.cookies.load(ignore_discard=True)
            except IOError:
                pass  # ignore if file doesn't exist yet
        else:
            self.cookies = cookielib.CookieJar()

    def _url(self, path, sr=None):
        """Helper for constructing URLs."""
        if not path.startswith('/'):
            path = '/' + path
        if sr:
            prefix = '%s/r/%s/' % (self.host, sr)
        else:
            prefix = self.host
        return '%s%s.json' % (prefix, path)

    def _post(self, url, **data):
        """Helper for making POST requests."""
        return self._request('POST', url, **data)

    def _get(self, url, **data):
        """Helper for making GET requests."""
        return self._request('GET', url, **data)

    def _request(self, method, url, **data):
        """Make an HTTP request."""
        # add modhash to data if it's not there already
        if self.modhash and 'uh' not in data:
            data = data.copy()
            data['uh'] = self.modhash

        # encode data; move it into URL if this is a GET request
        data = urllib.urlencode(data)
        if method == 'GET':
            if '?' in url:
                url = '%s&%s' % (url, data)
            else:
                url = '%s?%s' % (url, data)
            data = None

        # make the request
        headers = {}
        if self.user_agent:
            headers['User-Agent'] = self.user_agent
        logging.info('request: %s %s', method, url)
        req = urllib2.Request(url, data, headers)
        self.cookies.add_cookie_header(req)
        opener = urllib2.build_opener(self.auth_handler)
        resp = opener.open(req)

        # save any cookies to the cookie jar
        self.cookies.extract_cookies(resp, req)
        try:
            self.cookies.save(ignore_discard=True)
        except (AttributeError, NotImplementedError):
            pass  # ignore

        # parse and return the response
        logging.info('content type: %s', resp.info()['Content-Type'])
        if resp.info()['Content-Type'] == 'text/plain':
            logging.info('returning plaintext')
            return resp.read()
        return json.load(resp)

    @property
    def logged_in(self):
        for cookie in self.cookies:
            if cookie.name == 'reddit_session':
                return True
        return False

    def log_in(self):
        """Sign into the site and get a reddit_session cookie.

        NOTE: this interacts with the terminal to get credentials
        """
        while not self.logged_in:
            user = raw_input('reddit username: ')
            password = getpass.getpass('reddit password: ')
            response = self._post(self._url('/api/login'),
                                  user=user, passwd=password)

        # fetch modhash
        response = self._get(self._url('/api/me'))
        self.modhash = response['data']['modhash']
        return True

    def flair_list(self, subreddit, batch_size=100):
        """Fetch all flair for a subreddit.

        Args:
          subreddit: str, name of the subreddit
          batch_size: int, number of users to fetch per HTTP request; the server
              likely supports a maximum of 1000 per request

        Yields:
          A 3-tuple of strings giving (username, flair text, flair css class).
          The client will automatically make further requests as this generator
          is consumed.
        """
        after = None
        while True:
            kw = dict(limit=batch_size)
            if after:
                kw['after'] = after
            result = self._get(self._url('/api/flairlist', sr=subreddit), **kw)
            after = result.get('next')
            for user in result.get('users', []):
                yield (user.get('user'), user.get('flair_text'),
                       user.get('flair_css_class'))
            if not after:
                break

    def flair(self, subreddit, user, text, css_class):
        """Set flair for a user in a subreddit.

        If the empty string is given for both text and css_class, then the
        effect should be the same as calling unflair for the same user.

        Args:
          subreddit: str, name of the subreddit
          user: str, name of the user
          text: str, text to use for flair (may be empty string)
          css_class: str, css class for this flair (may be empty string)

        Returns: None
        """
        self._post(self._url('/api/flair', sr=subreddit),
                   name=user, text=text, css_class=css_class)

    def unflair(self, subreddit, user):
        """Remove flair from a user in a subreddit."""
        self._post(self._url('/api/unflair', sr=subreddit), name=user)

    def flaircsv(self, subreddit, flair):
        """Post a batch of flair settings to a subreddit.

        Args:
          subreddit: str, name of the subreddit
          flair: sequence of flair tuples, where each tuple contains three
            strings giving the username, flair text, and flair css class
            respectively. If both the text and css class are the empty string
            for a particular user, then that user's flair will be removed.

        Returns:
          A list of result dictionaries, one for each element of flair. Each
          dictionary contains the following "fields":

            ok: bool, whether this flair entry was successfully committed
            status: str, description of whether this entry was added, removed,
              or skipped
            errors: dict of str -> str, describes errors for particular fields
              in the entry (or the entire entry itself), which caused skipping
              of this entry
            warnings: dict of str -> str, describes problems for particular
              fields which affected how this entry was committed
        """
        f = StringIO()
        csv_f = csv.writer(f)
        for row in flair:
            csv_f.writerow(row)
        return self._post(self._url('/api/flaircsv', sr=subreddit),
                          flair_csv=f.getvalue())
