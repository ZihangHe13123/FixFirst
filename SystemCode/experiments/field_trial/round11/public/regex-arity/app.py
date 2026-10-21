import re

def matches():
    return re.fullmatch(r"[A-Z]+") is not None
