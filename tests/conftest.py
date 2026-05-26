pytest_plugins: list[str] = []

collect_ignore = ['test_adversarial.py']
pytest_plugins: list[str] = []

# test_adversarial.py is a standalone script (not pytest-collectible).
# Run with: PYTHONPATH=src python tests/test_adversarial.py
# The full test entry point is: PYTHONPATH=src python tests/run_tests.py
collect_ignore = ['test_adversarial.py']
