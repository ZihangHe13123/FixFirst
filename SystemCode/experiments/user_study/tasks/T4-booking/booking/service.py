from .config import load


def book(seats):
    settings = load()
    if not 0 < seats <= settings["max_seats"]:
        raise ValueError(f"book between 1 and {settings['max_seats']} seats")
    return {"seats": seats, "currency": settings["currency"]}


def price(seats, unit_price):
    return {"amount": seats * unit_price, "currency": load()["currency"]}
