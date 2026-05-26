pytest_plugins: list[str] = []

# test_adversarial.py is a standalone script (not pytest-collectible).
# Run with: PYTHONPATH=src python tests/test_adversarial.py
collect_ignore = ['test_adversarial.py']

