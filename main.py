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
        level=logging.DEBUG,
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

    def get_preferred_interval_indices(shares, target_ratios):
        not_saturated = []
        not_null = []
        for i in range(len(shares)):
            if shares[i] < target_ratios[i][1]:
                not_saturated.append(i)
            if target_ratios[i][1] > 0:
                not_null.append(i)
        if not_saturated:
            return not_saturated
        return not_null

    with open(settings["password_file"]) as fin:
        password = fin.read().strip()

    client = Client(
        username=settings["username"],
        password=password,
        session_path=settings["session_path"],
        code_path=settings["sms_code_path"],
        token_path=settings["token_path"],
        interest_interval_ends=interest_interval_ends
    )

    loans = client.get_available_loans(max_months=settings["max_months"])

    invested_loans = set(inv["loanId"] for inv in client.get_portfolio())

    skipped = 0
    for loan in loans:
        if loan["id"] in invested_loans:
            skipped += 1
            continue
        interest_rate = loan["interestRate"]

        preferred_interval_indices = get_preferred_interval_indices(
            client.get_bin_shares(),
            settings["target_ratios"]
        )

        index = client.get_bin_index(interest_rate)
        if index in preferred_interval_indices:
            r = client.make_investment(
                loan["id"], interest_rate, settings["investment_amount"]
            )
            if r.status_code == 200:
                logging.info(
                    "Invested in loan {} (interest rate {})".format(
                        loan["id"], interest_rate
                    )
                )
            else:
                response = json.loads(r.text)
                if response.get("error") == "insufficientBalance":
                    logging.info("Not enough money")
                    break
                logging.warning(r.text)
        time.sleep(1)
    logging.info("Skipped {} out of {} loans".format(skipped, len(loans)))

    client.save()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("{}".format(e))
