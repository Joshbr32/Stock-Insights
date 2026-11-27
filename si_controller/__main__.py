"""Entry point: ``python -m si_controller run|status|start|stop|restart|logs|events``."""
import sys

from .cli import main

sys.exit(main())
