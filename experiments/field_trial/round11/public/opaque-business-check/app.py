def evaluate(value):
    if value < 10:
        raise ValueError("input rejected")
    return value * 2
