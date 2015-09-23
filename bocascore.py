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
import ConfigParser

from bs4 import BeautifulSoup

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
    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.cj = None
        self.opener = None
        self.loginok = False

    def login(self):
        self.cj = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1')]
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

def load_boards(filename):
    cfg = ConfigParser.SafeConfigParser()
    cfg.read(filename)

    boards = []

    for sec in cfg.sections():
        boardtype = cfg.get(sec, 'type')

        if cfg.get(sec, 'enabled') != '1':
            continue

        if boardtype == 'boca':
            B = BocaScoreboard(cfg.get(sec, 'url'), cfg.get(sec, 'user'), cfg.get(sec, 'pass'))
        else:
            raise Exception("unknown board type " + board + " in section " + sec)

        boards.append(B)

    return boards

def main():
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = "config.txt"

    boards = load_boards(filename)

    scores = [b.get_scoreboard() for b in boards]


if __name__ == '__main__':
    main()
