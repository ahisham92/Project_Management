"""Carmen: a language model with hands, bounded to one project.

She has a name because people talk to her — "ask Carmen" is a thing somebody
says to a colleague, and "invoke the assistant" is not.
"""

from .runner import Answer, ask, staged_summary  # noqa: F401
from .tools import CATALOGUE, READ_ONLY, WRITES, describe, run  # noqa: F401

NAME = "Carmen"
ROLE = "project assistant"
