import logging
import sys
import structlog
from asgi_correlation_id import correlation_id

def setup_logging():
    # 1. Standard python logging configuration
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    # 2. Configure structlog to output as JSON with relevant context
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Add correlation id (X-Request-ID) to the log context
            lambda logger, log_method, event_dict: add_correlation_id(logger, log_method, event_dict),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

def add_correlation_id(logger, log_method, event_dict):
    """Add correlation ID from the current context to the log entry."""
    req_id = correlation_id.get()
    if req_id:
        event_dict["request_id"] = req_id
    return event_dict
