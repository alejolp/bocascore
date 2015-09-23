#!/usr/bin/env python
# coding: utf-8

import os
import sys
import urllib
import urllib2
import cookielib
import hashlib
import pprint
import string
import json
import gzip
import StringIO
import ConfigParser

from bs4 import BeautifulSoup

ASCII_UPPERCASE = set(string.ascii_uppercase)

HTTP_USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1'

def fix_malformed_row(S):
    # BOCA HTML is malformed. The first TD is never closed, and BeautifulSoup breaks
    """
    <tr class="sitegroup2"><td>1</td>
  <td nowrap>alejo/1 <td>Alejo</td><td nowrap><img alt="Red:" width="18" src="/boca/balloons/71db27c5c4d1a01e65239eb1b9d1f667.png" /><font size="-2">1/104</font>
</td>  <td nowrap>1 (104)</td>
 </tr>
    """
    i = 0 
    while i < len(S):
        p = S.find("<td", i)
        if p < 0:
            break
        pa = S.find("<td", p + 1)
        pb = S.find("</td", p)

        if (pa < 0) or (pb < 0):
            break

        if pa < pb:
            # We've found a <td which was not closed.
            S = S[:pa] + "</td>" + S[pa:]
            i = pa
        else:
            i = pb

    return S

class BocaScoreboard:
    def __init__(self, base_url, username, password, name):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.name = name
        self.cj = None
        self.opener = None
        self.loginok = False

    def login(self):
        self.cj = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [('User-Agent', HTTP_USER_AGENT)]
        self.loginok = False

        # First, get the secret login salt
        resp = self.opener.open(self.base_url + '/index.php')
        soup = BeautifulSoup(resp.read(), 'html.parser')
        salt = None

        for script in soup.find_all('script'):
            text = script.get_text()
            if u"computeHASH" in text:
                salt = [x.split(u"'")[1] for x in text.split() if u"js_myhash(document.form1.password.value)" in x][0]
                break

        # With the salt make the login parameters
        encoded_username = self.username
        encoded_password = hashlib.sha256( hashlib.sha256(self.password).hexdigest() + salt ).hexdigest()

        login_data = urllib.urlencode({'name' : encoded_username, 'password' : encoded_password})
        
        # Try to login
        resp = self.opener.open(self.base_url + '/index.php?' + login_data)
        resptext = resp.read()
        soup = BeautifulSoup(resptext, 'html.parser')

        for script in soup.find_all('script'):
            text = script.get_text().strip()
            if text == u"document.location='score/index.php';":
                self.loginok = True
                break
            elif u'alert' in text:
                raise Exception(u"Login error: " + text)

        if not self.loginok:
            raise Exception("Unknown login error: username or password invalid")

    def get_scoreboard(self):
        if not self.loginok:
            self.login()

        resp = self.opener.open(self.base_url + '/score/index.php')
        resptext = resp.read()
        soup = BeautifulSoup(fix_malformed_row( resptext ), 'html.parser')

        table = soup.find(id=u'myscoretable')
        rows = list(table.find_all('tr'))

        L = []

        row0 = [x.get_text().strip() for x in rows[0].find_all('td')]

        for group in rows:
            if u"sitegroup1" in group.attrs.get('class', ''):
                r = [x.get_text().strip() for x in group.find_all('td')]
                assert len(r) == len(row0)
                L.append(dict(zip(row0, r)))

        return L

class JsonScoreboard:
    def __init__(self, base_url, name):
        self.base_url = base_url
        self.name = name
        self.cj = None
        self.opener = None
        self.loginok = False

    def login(self):
        self.cj = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [('User-Agent', HTTP_USER_AGENT)]
        self.loginok = True

    def get_scoreboard(self):
        if not self.loginok:
            self.login()

        resp = self.opener.open(self.base_url)
        resptext = resp.read()

        try:
            return json.loads(resptext)
        except ValueError:
            pass
            
        str_file_handle = StringIO.StringIO( resptext )
        gzip_file_handle = gzip.GzipFile(fileobj=str_file_handle)
        return json.loads(gzip_file_handle.read())

def load_boards(cfg):

    boards = []

    for sec in cfg.sections():
        if sec in ['config']:
            continue

        boardtype = cfg.get(sec, 'type')

        if cfg.get(sec, 'enabled') != '1':
            continue

        if boardtype == 'boca':
            B = BocaScoreboard(cfg.get(sec, 'url'), cfg.get(sec, 'user'), cfg.get(sec, 'pass'), cfg.get(sec, 'name'))
        elif boardtype == 'json':
            B = JsonScoreboard(cfg.get(sec, 'url'), cfg.get(sec, 'name'))
        else:
            raise Exception("unknown board type " + board + " in section " + sec)

        boards.append(B)

    return boards

def team_points_key(t):
    solved = 0
    penalty = 0

    for k in t:
        if k.upper() in ASCII_UPPERCASE:
            ss = t.get(k).split('/')
            if len(ss) == 2 and ss[0].isdigit() and ss[1].isdigit():
                solved  += 1
                penalty += int(ss[1])

    return (solved, -penalty)

def unify_scoreboards(scores):
    allkeys = set()

    for board, s in scores:
        for t in s:
            allkeys = allkeys.union(t.keys())

    allteams = []

    for board, s in scores:
        for t in s:
            t2 = dict([(k, t.get(k, u'')) for k in allkeys])
            if u'Site Name' not in t2:
                t2[u'Site Name'] = unicode(board.name)
            allteams.append(t2)

    allteams.sort(key=team_points_key, reverse=True)

    return allteams

def output_html(filename_output, unified):
    with open(filename_output, 'w') as f:
        f.write("""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Scoreboard Torneo Argentino de Programaci&oacute;n</title>
</head>
<body>
<h1>Scoreboard Torneo Argentino de Programaci&oacute;n</h1>
  <table>
""")
        if len(unified) > 0:
            keys = sorted(unified[0].keys(), key=(lambda x: len(x)))
            if '#' in keys:
                keys.remove('#')

            f.write("<tr>")

            f.write("<th>#</th>")

            for k in keys:
                f.write("<th>" + k.encode('utf8') + "</th>")
            f.write("</tr>")

            for i, team in enumerate(unified, 1):
                f.write("<tr>")
                f.write("<td>" + str(i) + "</td>")
                for k in keys:
                    f.write("<td>" + team[k].encode('utf8') + "</td>")
                f.write("</tr>")
        f.write("""  </table></body></hmtl>""")

def output_json(filename_output, unified, compress):
    data = json.dumps(unified, sort_keys=True, indent=1)

    if compress:
        f = gzip.open(filename_output, 'wb')
        f.write(data)
        f.close()
    else:
        f = open(filename_output, 'w')
        f.write(data)
        f.close()

def main():
    filename_config = sys.argv[1]

    cfg = ConfigParser.SafeConfigParser()
    cfg.read(filename_config)

    boards = load_boards(cfg)

    scores = []

    for b in boards:
        try:
            scores.append((b, b.get_scoreboard()))
        except Exception, e:
            print e

    unified = unify_scoreboards( scores )

    # pprint.pprint( unified )

    output_file_prefix = cfg.get('config', 'output_file_prefix')

    output_html(output_file_prefix + '.html', unified)
    output_json(output_file_prefix + '.json', unified, False)
    output_json(output_file_prefix + '.json.gz', unified, True)

if __name__ == '__main__':
    main()
