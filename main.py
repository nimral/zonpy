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

    interest_interval_ends = []
    last_end = 0
    for end, share in settings["target_ratios"]:
        if end < 0:
            logging.error("Interval end is < 0 ({})".format(end))
            return 1
        if end > 1:
            logging.error("Interval end is > 0 ({})".format(end))
            return 1
        if end <= last_end:
            logging.error(
                "Interval end is <= to the last one ({} <= {})"
                .format(end, last_end)
            )
            return 1
        last_end = end
        interest_interval_ends.append(end)

    if interest_interval_ends[-1] != 1:
        logging.error("Last interval end must be equal to 1")
        return 1

    def get_interval_index(x):
        for end in interest_interval_ends:
            if x <= end:
                return end

    with open(settings["password_file"]) as fin:
        password = fin.read().strip()

    client = Client(settings["username"], password, interest_interval_ends)

    balance = client.get_balance()
    logging.info("Balance {:.2f}".format(balance))

    if balance >= settings["investment_amount"]:
        loans = client.get_available_loans(max_months=settings["max_months"])

        invested_loans = set(inv["loanId"] for inv in client.get_portfolio())

        skipped = 0
        for loan in loans:
            if loan["id"] in invested_loans:
                skipped += 1
                continue
            interest_rate = loan["interestRate"]
            index = client.get_bin_index(interest_rate)
            bin_share = client.get_bin_shares()[index]
            target_bin_share = settings["target_ratios"][index][1]
            if bin_share <= target_bin_share and target_bin_share > 0:
                r = client.make_investment(
                    loan["id"], interest_rate, settings["investment_amount"]
                )
                if r.status_code == 200:
                    logging.info(
                        "Invested in loan {} (interest rate {})".format(
                            loan["id"], interest_rate
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
