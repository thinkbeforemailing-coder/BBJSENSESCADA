import config_cache
import device_status
import gateway_commands
import offline_buffer


# Regression test for a real production incident: offline_buffer.py,
# config_cache.py, gateway_commands.py, and device_status.py each used
# to call setup_logger() independently, creating a second/third/fourth
# RotatingFileHandler on the SAME log file as the main process logger.
# When that file crossed its 5MB rollover threshold, multiple handlers
# raced to rotate it, hit a Windows file-locking conflict, and hung the
# entire gateway process for 20+ minutes with zero telemetry.
#
# The fix: these modules use plain logging.getLogger("parent.child")
# with no handler of their own, relying on propagation into the
# parent's single already-configured handler. This test guards against
# reintroducing an owned handler on any of them.

MODULES_THAT_MUST_NOT_OWN_A_HANDLER = [
    offline_buffer,
    config_cache,
    gateway_commands,
    device_status,
]


def test_shared_utility_loggers_have_no_handlers_of_their_own():
    for module in MODULES_THAT_MUST_NOT_OWN_A_HANDLER:
        assert module.logger.handlers == [], (
            f"{module.__name__}.logger owns handler(s): "
            f"{module.logger.handlers!r} -- this module should log "
            f"via propagation into its parent logger instead, not its "
            f"own RotatingFileHandler on a file another logger also "
            f"writes to."
        )


def test_shared_utility_loggers_propagate():
    for module in MODULES_THAT_MUST_NOT_OWN_A_HANDLER:
        assert module.logger.propagate is True, (
            f"{module.__name__}.logger has propagate=False, so its "
            f"messages would go nowhere without its own handler."
        )
