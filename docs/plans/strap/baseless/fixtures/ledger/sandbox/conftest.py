"""Marks the sandbox root for pytest.

``pythonpath = .`` in ``pytest.ini`` puts the sandbox folder on sys.path, so
the tests import ``ledger`` under any import mode (``prepend`` or ``importlib``).
"""
