import logging
import sys

_logger = None

def get_logger(name='cs-market'):
    global _logger
    if _logger is None:
        _logger = logging.getLogger(name)
        _logger.setLevel(logging.DEBUG)
        if not _logger.handlers:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter(
                '[%(asctime)s] %(levelname)-5s %(name)s: %(message)s',
                datefmt='%H:%M:%S'
            ))
            _logger.addHandler(h)
    return _logger
