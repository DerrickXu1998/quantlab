"""Suite-wide defaults.

Auth (feature 007) defaults ON in production, but the pre-auth suite asserts
behavior from before accounts existed. Run it with auth off; the dedicated
auth tests (tests/unit/test_auth.py, tests/contract/test_auth_contract.py)
turn it back on per app via ``create_app(..., auth_enabled=True)``.
"""

import os

os.environ.setdefault("QUANTLAB_AUTH", "off")
