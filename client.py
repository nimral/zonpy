import json
import logging
from datetime import datetime as dt
from datetime import timedelta
from collections import defaultdict

import requests


def d(r):
    return json.loads(r.text)


class Client:
    page_size = 100

    def __init__(self, username, password, url_prefix="https://api.zonky.cz"):
        self.cached_portfolio = None
        self.cached_rating_shares = None
        self.ratings = None
        self.access_token = None
        self.refresh_token = None
        self.url_prefix = url_prefix
        self.balance = None

        self.auth(username, password)
        self.set_rating_amounts()

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

    def get_available_loans(self, min_remaining_investment=5000):
        logging.debug("Get loans")
        r = requests.get(
            "{}/loans/marketplace?remainingInvestment__gt={}&"
            .format(self.url_prefix, min_remaining_investment),
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
            "?fields=loanId,rating,remainingPrincipal".format(self.url_prefix),
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

    def set_rating_amounts(self):
        logging.debug("Set rating amounts")
        portfolio = self.get_portfolio()
        self.sum_invested = 0
        self.ratings = defaultdict(lambda: 0)
        for inv in portfolio:
            self.ratings[inv["rating"]] += inv["remainingPrincipal"]
            self.sum_invested += inv["remainingPrincipal"]

    def get_rating_shares(self):
        if self.balance is None:
            self.get_balance()
        sum_money = self.balance + self.sum_invested
        if self.cached_rating_shares is None:
            logging.debug("Cache rating shares")
            if self.ratings is None:
                self.set_rating_amounts()
            self.cached_rating_shares = {
                k: v / sum_money for k, v in self.ratings.items()
            }
        return self.cached_rating_shares

    def make_investment(self, loan_id, rating, amount):
        logging.info(
            "Make investment {} {} {}".format(loan_id, rating, amount)
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

        if self.ratings is not None:
            if r.status_code == 200:
                self.ratings[rating] += amount
                self.sum_invested += amount
                self.cached_portfolio.append({
                    "loanId": loan_id,
                    "rating": rating,
                    "amount": amount,
                })
                self.cached_rating_shares = None
                self.balance -= amount
                logging.info("Balance {}".format(self.balance))

        return r
