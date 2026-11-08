"""Synthetic input helpers shared across adapter regressions."""

def fake_crypt(value, *, decrypt=False):
    return bytes(c ^ 123 for c in value)
