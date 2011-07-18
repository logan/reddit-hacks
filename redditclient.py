import cookielib
import getpass
import json
import urllib
import urllib2

class RedditClient:
    def __init__(self, host='http://reddit.com', cookie_file=None,
            http_user=None, http_password=None):
        while host.endswith('/'):
            host = host[:-1]
        self.host = host

        self.password_manager = urllib2.HTTPPasswordMgrWithDefaultRealm()
        if http_user:
            self.password_manager.add_password(None, self.host,
                                               http_user, http_password)
        self.auth_handler = urllib2.HTTPDigestAuthHandler(self.password_manager)

        if cookie_file:
            self.cookies = cookielib.LWPCookieJar(cookie_file)
            try:
                self.cookies.load(ignore_discard=True)
            except IOError:
                pass  # ignore if file doesn't exist yet
        else:
            self.cookies = cookielib.CookieJar()

    def _url(self, path, sr=None):
        if not path.startswith('/'):
            path = '/' + path
        if sr:
            prefix = '%s/r/%s/' % (self.host, sr)
        else:
            prefix = self.host
        return '%s%s.json' % (prefix, path)

    def _post(self, url, **data):
        return self._request('POST', url, **data)

    def _get(self, url, **data):
        return self._request('GET', url, **data)

    def _request(self, method, url, **data):
        data = urllib.urlencode(data)
        if method == 'GET':
            if '?' in url:
                url = '%s&%s' % (url, data)
            else:
                url = '%s?%s' % (url, data)
            data = None
        req = urllib2.Request(url, data)
        self.cookies.add_cookie_header(req)
        opener = urllib2.build_opener(self.auth_handler)
        resp = opener.open(req)
        self.cookies.extract_cookies(resp, req)
        return json.load(resp)

    def log_in(self):
        for cookie in self.cookies:
            if cookie.name == 'reddit_session':
                logged_in = True
                break
        else:
            logged_in = False

        if not logged_in:
            user = raw_input('reddit username: ')
            password = getpass.getpass('reddit password: ')
            response = self._post(self._url('/api/login'),
                                  user=user, passwd=password)
        else:
            response = self._get(self._url('/api/me'))

        for cookie in self.cookies:
            if cookie.name == 'reddit_session':
                try:
                    self.cookies.save(ignore_discard=True)
                except NotImplementedError:
                    pass  # ignore
                return True
        return False

    def flair_list(self, subreddit, batch_size=100):
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
        self._post(self._url('/api/flair', sr=subreddit),
                   name=user, text=text, css_class=css_class)

    def unflair(self, subreddit, user):
        self._post(self._url('/api/unflair', sr=subreddit), name=user)
