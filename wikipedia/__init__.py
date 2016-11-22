try:
    from .wikipedia import *
except ImportError:
    # import will fail during setup.py in clean venv
    pass
from .exceptions import *
from .version import *


__version__ = get_version()
