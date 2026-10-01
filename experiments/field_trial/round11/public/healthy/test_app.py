from app import answer

def test_answer():
    assert answer(3) == 8
    assert answer(-1) == 0
