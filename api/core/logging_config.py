import logging
import json
from datetime import datetime
from pathlib import Path

# Everything logging itself puts on a LogRecord. Whatever is left over came
# from a caller's extra={...}, which is the part worth printing.
_STANDARD_RECORD_ATTRS = frozenset({
    'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
    'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
    'message', 'msg', 'name', 'pathname', 'process', 'processName',
    'relativeCreated', 'stack_info', 'thread', 'threadName', 'taskName',
})


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'timestamp': datetime.now().isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # `logger.error("...", extra={'error': msg})` sets record.error, NOT
        # record.extra_data. This only read extra_data, so every extra passed
        # anywhere in this service was silently discarded.
        #
        # That is not cosmetic. On 2026-09-19 a batch upload failed on
        # "CSV validation failed" and the reason - which column was missing -
        # went into extra and was dropped, leaving a log line that says
        # something went wrong and refuses to say what. Diagnosing it meant
        # reading the source to find that the two branches which log that exact
        # message differ only by line number.
        extras = {
            key: value for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith('_')
        }
        # Kept for any caller still using the old convention explicitly.
        extras.pop('extra_data', None)
        if hasattr(record, 'extra_data') and isinstance(record.extra_data, dict):
            extras.update(record.extra_data)

        for key, value in extras.items():
            # A log line must never be the thing that raises. Anything that is
            # not JSON-serialisable is rendered rather than thrown.
            try:
                json.dumps(value)
                log_data[key] = value
            except (TypeError, ValueError):
                log_data[key] = repr(value)

        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)

def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)
    
    # File handler for general logs
    general_handler = logging.FileHandler('logs/batch_processing.log')
    general_handler.setFormatter(JSONFormatter())
    logger.addHandler(general_handler)
    
    # File handler for errors
    error_handler = logging.FileHandler('logs/errors.log')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JSONFormatter())
    logger.addHandler(error_handler)
    
    return logger 