import logging


def setup_logging():
    logger = logging.getLogger("mybot")
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", "%H:%M:%S"
        )
    )

    logger.addHandler(handler)
    logger.propagate = False  # Important
