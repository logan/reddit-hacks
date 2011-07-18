#!/usr/bin/python

import argparse
import csv
import getpass
import htmlentitydefs
import re
import sys

import redditclient

def parse_args():
    parser = argparse.ArgumentParser(
        add_help=False,
        description='sync subreddit flair with with a csv file')

    parser.add_argument('subreddit', metavar='SUBREDDIT')
    parser.add_argument('csvfile', metavar='CSVFILE')

    parser.add_argument('--help', action='help', default=argparse.SUPPRESS,
                        help='show this help message and exit')
    parser.add_argument('-A', '--http_auth', default=False, const=True,
                        action='store_const',
                        help='set if HTTP basic authentication is needed')
    parser.add_argument('-b', '--batch_size', type=int, default=100,
                        help='number of users to read at a time from the site')
    parser.add_argument('-c', '--cookie_file',
                        help='if given, save session cookie in this file')
    parser.add_argument('-h', '--host', default='http://reddit.com',
                        help='URL of reddit API server')
    return parser.parse_args()

def ynprompt(prompt):
    return raw_input(prompt).lower().startswith('y')

def log_in(host, cookie_file, use_http_auth):
    if use_http_auth:
        http_user = raw_input('HTTP auth username: ')
        http_password = getpass.getpass('HTTP auth password: ')
        options = dict(http_user=http_user, http_password=http_password)
    else:
        options = {}
    client = redditclient.RedditClient(host, cookie_file, **options)
    while not client.log_in():
        print 'login failed'
    return client

def flair_from_csv(path):
    f = csv.reader(file(path))
    # skip header row
    f.next()
    return dict((r[0], (r[1], r[2])) for r in f)

def flair_from_reddit(client, subreddit, batch_size):
    def u(html):
        if html is None:
            return None
        def decode_entity(m):
            text = m.group(0)
            if text.startswith('&#'):
                try:
                    if text.startswith('&#x'):
                        return unichr(int(text[3:-1]), 16)
                    else:
                        return unichr(int(text[2:-1]))
                except ValueError:
                    pass  # ignore
            else:
                try:
                    return unichr(htmlentitydefs.name2codepoint[text[1:-1]])
                except KeyError:
                    pass  # ignore
            # fallthrough; on error just return original text
            return text
        return re.sub(r'&#?\w+;', decode_entity, html)

    return dict((u(r[0]), (u(r[1]), u(r[2])))
                for r in client.flair_list(subreddit, batch_size=batch_size))

def diff_flair(left, right):
    """returns: (modifications, additions, deletions)"""
    left_users = frozenset(left)
    right_users = frozenset(right)
    common_users = left_users & right_users
    added_users = right_users - left_users
    removed_users = left_users - right_users
    modifications = []
    for u in common_users:
        if left[u] != right[u]:
            modifications.append((u, right[u][0], right[u][1]))
    additions = [(u, right[u][0], right[u][1]) for u in added_users]
    return modifications, additions, removed_users

def main():
    config = parse_args()

    print 'Parsing csv file: %s ...' % config.csvfile
    csv_flair = flair_from_csv(config.csvfile)

    print 'Connecting to %s ...' % config.host
    client = log_in(config.host, config.cookie_file, config.http_auth)

    print 'Fetching current flair from site ...'
    reddit_flair = flair_from_reddit(client, config.subreddit,
                                     config.batch_size)

    print 'Computing differences ...'
    modifications, additions, deletions = diff_flair(reddit_flair, csv_flair)

    print '\nmodifications:'
    print '\n'.join(['  %s -> %r %s' % mod for mod in modifications])
    print '\nadditions:'
    print '\n'.join(['  %s -> %r %s' % mod for mod in additions])
    print '\ndeletions:'
    print '\n'.join(['  %s' % u for u in deletions])

    if ((modifications or additions or deletions)
        and ynprompt('\napply the above changes? [y/N] ')):

        for user, text, css in modifications + additions:
            print 'setting flair for user %s ...' % user
            client.flair(config.subreddit, user, text, css)

        for user in deletions:
            print 'deleting flair for user %s ...' % user
            client.unflair(config.subreddit, user)

        print 'Done!'

if __name__ == '__main__':
    main()
