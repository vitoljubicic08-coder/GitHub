import logging

# keep expected warnings (simulated outages, failed logins) out of the test output
logging.getLogger("quotebook").addHandler(logging.NullHandler())
logging.getLogger("quotebook").propagate = False
