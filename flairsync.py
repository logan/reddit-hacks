#!/usr/bin/python

"""Tool for syncing flair on reddit with a local csv file.

The first line of the csv file will be ignored (assumed to be a header).

Example:

$ cat test.csv
user,text,css
intortus,zzr600,kawasaki
$ ./flairsync.py -c intortus.cookie example test.csv
Parsing csv file: test.csv ...
Connecting to http://www.reddit.com ...
reddit username: intortus
reddit password: 
Fetching current flair from site ...
Computing differences ...

modifications:
  intortus -> 'zzr600' kawasaki

deletions:


apply the above changes? [y/N] y
posting flair for users 1-1/1
Done!
$ cat null.csv
user,text,css
$ ./flairsync.py -c intortus.cookie example null.csv
Parsing csv file: null.csv ...
Connecting to http://www.reddit.com ...
Fetching current flair from site ...
Computing differences ...

modifications:


deletions:
  intortus

apply the above changes? [y/N] y
posting flair for users 1-1/1
Done!
"""

import argparse
import csv
import getpass
import htmlentitydefs
import logging
import os
import re
import sys
import time

import redditclient

def parse_args():
    parser = argparse.ArgumentParser(
        description='sync subreddit flair with with a csv file')

    parser.add_argument('subreddit', metavar='SUBREDDIT')
    parser.add_argument('csvfile', metavar='CSVFILE')

    parser.add_argument('-A', '--http_auth', default=False, const=True,
                        action='store_const',
                        help='set if HTTP basic authentication is needed')
    parser.add_argument('-b', '--batch_size', type=int, default=100,
                        help='number of users to read at a time from the site')
    parser.add_argument('-c', '--cookie_file',
                        help='if given, save session cookie in this file')
    parser.add_argument('-H', '--host', default='http://www.reddit.com',
                        help='URL of reddit API server')
    parser.add_argument('-v', '--verbose', default=False, const=True,
                        action='store_const',
                        help='emit more verbose logging')
    return parser.parse_args()

def ynprompt(prompt):
    return raw_input(prompt).lower().startswith('y')

def log_in(host, cookie_file, use_http_auth):
    if use_http_auth:
        http_user = raw_input('HTTP auth username: ')
        http_password = getpass.getpass('HTTP auth password: ')
        options = dict(_http_user=http_user, _http_password=http_password)
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
    return dict((r[0], (r[1], r[2])) for r in f if r[1] or r[2])

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
    """returns: (modifications, deletions)"""
    left_users = frozenset(left)
    right_users = frozenset(right)
    common_users = left_users & right_users
    added_users = right_users - left_users
    removed_users = left_users - right_users
    modifications = [(u, right[u][0], right[u][1])
                     for u in common_users if left[u] != right[u]]
    modifications.extend((u, right[u][0], right[u][1]) for u in added_users)
    return modifications, removed_users

def configure_logging():
    class LoggingFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            timestamp = time.strftime(datefmt)
            return timestamp % dict(ms=(1000 * record.created) % 1000)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = LoggingFormatter(
        '%(levelname).1s%(asctime)s: %(message)s',
        '%m%d %H:%M:%S.%%(ms)03d')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

def summarize_batch_result(lines, result):
    failed_entries = [e for e in result if not e['ok']]
    if failed_entries:
        print 'WARNING: %d entr%s skipped:' % (
            len(failed_entries),
            'y was' if len(failed_entries) == 1 else 'ies were')

    for l, e in zip(lines, result):
        if not e['ok']:
            print '  entry: %s' % ','.join(l)
            for m in e['errors'].itervalues():
                print '    - %s' % m

    # print out any warnings for items that were committed
    for l, e in zip(lines, result):
        if e['ok'] and e['warnings']:
            for m in e['warnings'].itervalues():
                print 'NOTE: entry %s: %s' % (','.join(l), m)

def main():
    config = parse_args()
    if config.verbose:
        configure_logging()

    print 'Parsing csv file: %s ...' % config.csvfile
    csv_flair = flair_from_csv(config.csvfile)

    print 'Connecting to %s ...' % config.host
    client = log_in(config.host, config.cookie_file, config.http_auth)

    print 'Fetching current flair from site ...'
    reddit_flair = flair_from_reddit(client, config.subreddit,
                                     config.batch_size)

    print 'Computing differences ...'
    modifications, deletions = diff_flair(reddit_flair, csv_flair)

    print '\nmodifications:'
    print '\n'.join(['  %s -> %r %s' % mod for mod in modifications])
    print '\ndeletions:'
    print '\n'.join(['  %s' % u for u in deletions])

    if ((modifications or deletions)
        and ynprompt('\napply the above changes? [y/N] ')):

        new_flair = modifications + [(u, '', '') for u in deletions]

        for i in xrange(0, len(new_flair), 100):
            print 'posting flair for users %d-%d/%d' % (
                i + 1, min(len(new_flair), i + 100), len(new_flair))
            result = client.flaircsv(config.subreddit, new_flair[i:i+100])
            logging.info('flaircsv result: %r', result)
            summarize_batch_result(new_flair, result)

        print 'Done!'

if __name__ == '__main__':
    main()
