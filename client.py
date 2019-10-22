import json
import time
import os
import pickle
import logging
from datetime import datetime as dt
from datetime import timedelta
from lxml import html

import requests


def d(r):
    return json.loads(r.text)


class Client:
    page_size = 100
    auth_header = {
        "Authorization": "Basic cm9ib3pvbmt5OjludEN6Y2lta0dBYXIzc2d6bXRlUVFNa"
                         "3FxOHVkRg=="
    }

    def __init__(self, username, password, session_path, code_path, token_path,
                 interest_interval_ends, url_prefix="https://api.zonky.cz"):
        self.cached_portfolio = None
        self.cached_bin_shares = None
        self.access_token = None
        self.url_prefix = url_prefix
        self.interest_interval_ends = interest_interval_ends
        self.bins = None

        self.session = None
        self.session_path = session_path
        self.code_path = code_path
        self.token_path = token_path
        self.expires = None

        self.username = username
        self.password = password

    def reauth(self):
        logging.debug("Reauth")
        values = {
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
            "scope": "SCOPE_APP_WEB",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic d2ViOndlYg=="
        }
        r = requests.post(
            "{}/oauth/token".format(self.url_prefix),
            data=values,
            headers=headers
        )
        self.set_tokens(r)

    def set_tokens(self, auth_code):
        logging.debug("Set tokens")
        r = requests.post(
            "{}/oauth/token".format(self.url_prefix),
            data={
                "code": auth_code,
                "redirect_uri": "https://app.zonky.cz/api/oauth/code",
                "grant_type": "authorization_code"
            },
            headers=self.auth_header
        )
        res = d(r)

        try:
            self.access_token = res["access_token"]
        except KeyError as e:
            logging.error("No access token in {}".format(res))
            raise e

        self.expires = timedelta(seconds=res["expires_in"]) + dt.now()

    def get_auth_code(self):
        logging.debug("Get auth code")
        if self.session is None:
            if os.path.isfile(self.session_path):
                with open(self.session_path, "rb") as fin:
                    self.session = pickle.load(fin)
            else:
                self.session = requests.Session()

        url = (
            "https://app.zonky.cz/api/public-login?redirect=L29hdXRoL2"
            "F1dGhvcml6ZT9jbGllbnRfaWQ9cm9ib3pvbmt5JnJlZGlyZWN0X3VyaT1o"
            "dHRwczovL2FwcC56b25reS5jei9hcGkvb2F1dGgvY29kZSZyZXNwb25zZV"
            "90eXBlPWNvZGUmc2NvcGU9U0NPUEVfQVBQX0JBU0lDX0lORk8lMjBTQ09Q"
            "RV9JTlZFU1RNRU5UX1JFQUQlMjBTQ09QRV9JTlZFU1RNRU5UX1dSSVRFJT"
            "IwU0NPUEVfUkVTRVJWQVRJT05TX1JFQUQlMjBTQ09QRV9SRVNFUlZBVElP"
            "TlNfV1JJVEUlMjBTQ09QRV9SRVNFUlZBVElPTlNfU0VUVElOR1NfV1JJVE"
            "UlMjBTQ09QRV9SRVNFUlZBVElPTlNfU0VUVElOR1NfUkVBRCUyMFNDT1BF"
            "X05PVElGSUNBVElPTlNfUkVBRCUyMFNDT1BFX05PVElGSUNBVElPTlNfV1"
            "JJVEUmc3RhdGU9ZGZmZGdkZmc%3D"
        )
        r = self.session.post(
            url,
            data={"email": self.username, "password": self.password}
        )

        if r.status_code // 100 != 2:
            logging.error(
                "Error status when getting auth code: {} {}"
                .format(r.status_code, r.text)
            )
            return None

        root = html.fromstring(r.text)
        title = root.xpath(".//title")[0].text

        if "SMS" in title:
            if "nepodařilo odeslat" in title:
                logging.error(
                    "No SMS code is going to arrive because of an error(?) "
                    "on the remote side."
                )
                return None

            sleep_time = 1 * 60
            logging.info(
                "Will wait for {} s and read SMS code from {}"
                .format(sleep_time, self.code_path)
            )
            time.sleep(sleep_time)

            if not os.path.isfile(self.code_path):
                logging.info(
                    "SMS code path {} does not exist".format(self.code_path)
                )
                return None
            with open(self.code_path) as fin:
                sms_code = fin.read().strip()

            r = self.session.post(url, data={"smsAuthCode": sms_code})
            if r.status_code // 100 != 2:
                logging.error(
                    "Error status when getting auth code by sms code: {} {}"
                    .format(r.status_code, r.text)
                )
                return None

            root = html.fromstring(r.text)

        auth_code = None
        try:
            auth_code = root.xpath(".//strong")[0].text
        except Exception:
            logging.warning(
                "Did not find auth code in the response: {}".format(r.text)
            )
            return None
        if len(auth_code) != 6:
            logging.warning(
                "Probably did not extract the right code: {} {}"
                .format(auth_code, r.text)
            )
        return auth_code

    def has_current_access_token(self):
        if self.expires is not None:
            if self.expires > dt.now() + timedelta(seconds=5):
                return True
        return False

    def make_yourself_logged_in(self):
        logging.debug("Make yourself logged in")
        if self.has_current_access_token():
            return

        self.load()
        if self.has_current_access_token():
            return

        auth_code = self.get_auth_code()
        self.set_tokens(auth_code)

    def save(self):
        logging.debug("Save")
        with open(self.token_path, "wb") as fout:
            pickle.dump(
                {
                    "access_token": self.access_token,
                    "expires": self.expires,
                },
                fout
            )

        if self.session is not None:
            with open(self.session_path, "wb") as fout:
                pickle.dump(self.session, fout)

    def load(self):
        logging.debug("Load")
        if os.path.isfile(self.token_path):
            with open(self.token_path, "rb") as fin:
                _d = pickle.load(fin)
                self.access_token = _d["access_token"]
                self.expires = _d["expires"]

        if os.path.isfile(self.session_path):
            with open(self.session_path, "rb") as fin:
                self.session = pickle.load(fin)

    def auth(self, username="", password=""):
        logging.debug("Auth")
        if self.access_token is not None:
            expires_in = self.expires - dt.now()
            if expires_in > timedelta(seconds=0):
                if expires_in < timedelta(seconds=120):
                    self.reauth()
                    return
                else:
                    logging.debug("We already have the token")
                    return

        r = requests.post(
            "{}/oauth/token".format(self.url_prefix),
            data={
                "grant_type": "password",
                "password": password,
                "username": username,
            },
            headers={
                "Authorization": "Basic d2ViOndlYg==",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        self.set_tokens(r)

    def get_available_loans(self, min_remaining_investment=5000,
                            max_months=84):
        logging.debug("Get loans")
        r = requests.get(
            "{}/loans/marketplace?nonReservedRemainingInvestment__gt={}&"
            "termInMonths__lte={}".format(
                self.url_prefix, min_remaining_investment, max_months
            ),
            headers={
                "X-Page": "0",
                "X-Size": "100",
            }
        )
        return d(r)

    def get_wallet(self):
        logging.debug("Get wallet")
        self.make_yourself_logged_in()
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(self.access_token)
        }
        r = requests.get(
            "{}/users/me/wallet".format(self.url_prefix),
            headers=headers
        )
        return d(r)

    def get_balance(self):
        balance = self.get_wallet()["availableBalance"]
        logging.info("Get balance: {}".format(balance))
        self.balance = balance
        return balance

    def get_portfolio_page(self, n):
        self.make_yourself_logged_in()
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(self.access_token),
            "X-Page": str(n),
            "X-Size": str(self.page_size),
        }
        r = requests.get(
            "{}/users/me/investments"
            "?fields=loanId,interestRate,remainingPrincipal"
            .format(self.url_prefix),
            headers=headers
        )
        return d(r)

    def get_portfolio(self):
        logging.debug("Get portfolio")
        if self.cached_portfolio is not None:
            return self.cached_portfolio
        investments = []
        i = 0
        while True:
            inv = self.get_portfolio_page(i)
            investments.extend(inv)
            if len(inv) < self.page_size:
                break
            i += 1

        self.cached_portfolio = investments
        return investments

    def get_bin_index(self, x):
        for i, end in enumerate(self.interest_interval_ends):
            if x <= end:
                return i

    def set_bin_amounts(self):
        logging.debug("Set bin amounts")
        portfolio = self.get_portfolio()
        self.sum_invested = 0
        self.bins = [0] * len(self.interest_interval_ends)
        for inv in portfolio:
            index = self.get_bin_index(inv["interestRate"])
            self.bins[index] += inv["remainingPrincipal"]
            self.sum_invested += inv["remainingPrincipal"]

    def get_bin_shares(self):
        logging.debug("Get bin shares")
        if self.cached_bin_shares is None:
            logging.debug("Cache bin shares")
            if self.bins is None:
                self.set_bin_amounts()
            self.cached_bin_shares = [x / self.sum_invested for x in self.bins]
        return self.cached_bin_shares

    def get_bin_share(self, interest_rate):
        return self.get_bin_shares()[self.get_bin_index(interest_rate)]

    def make_investment(self, loan_id, interest_rate, amount):
        logging.info(
            "Make investment {} {} {}".format(loan_id, interest_rate, amount)
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(self.access_token)
        }
        r = requests.post(
            "{}/marketplace/investment".format(self.url_prefix),
            data=json.dumps({
                "amount": amount,
                "loanId": str(loan_id),
                "captcha_response": "1213",
            }),
            headers=headers
        )

        if self.bins is not None:
            if r.status_code == 200:
                self.bins[self.get_bin_index(interest_rate)] += amount
                self.sum_invested += amount
                self.cached_portfolio.append({
                    "loanId": loan_id,
                    "interestRate": interest_rate,
                    "amount": amount,
                })
                self.cached_bin_shares = None
        return r
