import json
import logging
from datetime import datetime as dt
from datetime import timedelta

import requests


def d(r):
    return json.loads(r.text)


class Client:
    page_size = 100

    def __init__(self, username, password, interest_interval_ends,
                 url_prefix="https://api.zonky.cz"):
        self.cached_portfolio = None
        self.cached_bin_shares = None
        self.access_token = None
        self.refresh_token = None
        self.url_prefix = url_prefix
        self.balance = None
        self.interest_interval_ends = interest_interval_ends
        self.bins = None

        self.auth(username, password)
        self.set_bin_amounts()

    def set_tokens(self, r):
        res = d(r)
        try:
            self.access_token = res["access_token"]
        except KeyError as e:
            logging.error("No access token in {}".format(res))
            raise e
        self.expires = timedelta(seconds=res["expires_in"]) + dt.now()
        self.refresh_token = res["refresh_token"]

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
                "scope": "SCOPE_APP_WEB",
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
        self.auth()
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
        self.auth()
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
        if self.cached_bin_shares is None:
            if self.balance is None:
                self.get_balance()
            sum_money = self.balance + self.sum_invested
            logging.debug("Cache bin shares")
            if self.bins is None:
                self.set_bin_amounts()
            self.cached_bin_shares = [x / sum_money for x in self.bins]
        return self.cached_bin_shares

    def get_bin_share(self, interest_rate):
        return self.get_bin_shares()[self.get_bin_index(interest_rate)]

    def make_investment(self, loan_id, interest_rate, amount):
        logging.info(
            "Make investment {} {} {}".format(loan_id, interest_rate, amount)
        )
        self.auth()
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
                self.balance -= amount
                logging.info("Balance {:.2f}".format(self.balance))

        return r
