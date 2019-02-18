import logging
import time
import json
import argparse

from client import Client


def main():
    parser = argparse.ArgumentParser(description="Invest on Zonky.cz")
    parser.add_argument(
        "--settings_path",
        type=str,
        required=True,
        help="Path to a json file with settings"
    )
    parser.add_argument(
        "--log_path",
        type=str,
        default=None,
        help="Path to a log file"
    )
    args = parser.parse_args()

    logging.basicConfig(
        filename=args.log_path,
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s'
    )
    logging.info("Running")

    with open(args.settings_path) as fin:
        settings = json.load(fin)

    if abs(sum(settings["target_ratios"].values()) - 1) > 0.0001:
        logging.error("Target shares do not sum to 1")
        return 1

    with open(settings["password_file"]) as fin:
        password = fin.read().strip()

    client = Client(settings["username"], password)

    balance = client.get_balance()
    logging.info("Balance {}".format(balance))

    if balance >= settings["investment_amount"]:
        loans = client.get_available_loans()

        invested_loans = set(inv["loanId"] for inv in client.get_portfolio())

        skipped = 0
        for loan in loans:
            if loan["id"] in invested_loans:
                skipped += 1
                continue
            rating = loan["rating"]
            rating_share = client.get_rating_shares()[rating]
            if rating_share <= settings["target_ratios"][rating]:
                r = client.make_investment(
                    loan["id"], rating, settings["investment_amount"]
                )
                if r.status_code == 200:
                    logging.info(
                        "Invested in loan {} (rating {})".format(
                            loan["id"], rating
                        )
                    )
                    balance -= settings["investment_amount"]
                    if balance < settings["investment_amount"]:
                        logging.info(
                            "Ran out of money ({:.2f} < {})"
                            .format(balance, settings["investment_amount"])
                        )
                        break
                else:
                    logging.warning(r.text)
            time.sleep(1)
        logging.info("Skipped {} out of {} loans".format(skipped, len(loans)))
    else:
        logging.info(
            "Not enough money ({:.2f} < {})"
            .format(balance, settings["investment_amount"])
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("{}".format(e))
