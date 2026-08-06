import os

# Must run before dynamic_modbus_poller/settings are imported by any
# test module -- both read BBJ_GATEWAY_KEY at import time and raise
# (dynamic_modbus_poller.py) or leave it None (settings.py) otherwise.
os.environ.setdefault("BBJ_GATEWAY_KEY", "test-key-for-pytest")
