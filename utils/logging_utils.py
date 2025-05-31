"""
Logging utilities for distributed rendering
Provides structured logging with different levels and output options
"""

import logging
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import bpy

class BlenderLogHandler(logging.Handler):
    """
    Custom log handler that outputs to Blender's console and reports
    """

    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))

    def emit(self, record):
        """Emit log record to Blender console"""
        try:
            msg = self.format(record)

            # Print to console
            print(msg)

            # Also try to show as Blender report for important messages
            if record.levelno >= logging.WARNING and hasattr(bpy.ops, 'ui'):
                try:
                    if record.levelno >= logging.ERROR:
                        report_type = {'ERROR'}
                    else:
                        report_type = {'WARNING'}

                    # This might not always work depending on context
                    bpy.ops.ui.reports_to_textblock()
                except:
                    pass  # Ignore if we can't show report

        except Exception:
            self.handleError(record)

class DistributedRenderLogger:
    """
    Main logger class for distributed rendering
    """

    _loggers: Dict[str, logging.Logger] = {}
    _log_file: Optional[Path] = None
    _debug_mode: bool = False

    @classmethod
    def setup_logging(cls,
                     log_file: Optional[Path] = None,
                     debug_mode: bool = False,
                     console_level: int = logging.INFO):
        """
        Setup logging configuration

        Args:
            log_file: Path to log file (optional)
            debug_mode: Enable debug logging
            console_level: Minimum level for console output
        """
        cls._log_file = log_file
        cls._debug_mode = debug_mode

        # Set root logger level
        root_level = logging.DEBUG if debug_mode else logging.INFO
        logging.getLogger().setLevel(root_level)

        # Clear existing handlers
        for logger in cls._loggers.values():
            logger.handlers.clear()

        # Setup console handler
        console_handler = BlenderLogHandler()
        console_handler.setLevel(console_level)

        # Setup file handler if specified
        file_handler = None
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s - [%(filename)s:%(lineno)d]'
            ))

        # Apply handlers to all existing loggers
        for logger in cls._loggers.values():
            logger.addHandler(console_handler)
            if file_handler:
                logger.addHandler(file_handler)

        # Log setup completion
        setup_logger = cls.get_logger('setup')
        setup_logger.info("Logging system initialized")
        if debug_mode:
            setup_logger.debug("Debug mode enabled")
        if log_file:
            setup_logger.info(f"Logging to file: {log_file}")

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Get logger instance for specific module

        Args:
            name: Logger name (typically __name__)

        Returns:
            Logger instance
        """
        if name not in cls._loggers:
            logger = logging.getLogger(f"distributed_render.{name}")

            # Set level based on debug mode
            level = logging.DEBUG if cls._debug_mode else logging.INFO
            logger.setLevel(level)

            # Add handlers if logging is already setup
            if hasattr(logging.getLogger(), 'handlers') and logging.getLogger().handlers:
                # Copy handlers from root logger setup
                for handler in logging.getLogger().handlers:
                    if isinstance(handler, (BlenderLogHandler, logging.FileHandler)):
                        logger.addHandler(handler)

            cls._loggers[name] = logger

        return cls._loggers[name]

    @classmethod
    def log_performance(cls, operation: str, duration: float, details: Optional[Dict[str, Any]] = None):
        """
        Log performance information

        Args:
            operation: Name of operation
            duration: Duration in seconds
            details: Additional details to log
        """
        logger = cls.get_logger('performance')

        msg = f"Operation '{operation}' completed in {duration:.3f}s"
        if details:
            detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
            msg += f" ({detail_str})"

        logger.info(msg)

    @classmethod
    def log_bucket_progress(cls, bucket_id: int, progress: float, status: str):
        """
        Log bucket rendering progress

        Args:
            bucket_id: Bucket identifier
            progress: Progress percentage (0-100)
            status: Current status
        """
        logger = cls.get_logger('bucket_progress')
        logger.info(f"Bucket {bucket_id:04d}: {progress:5.1f}% - {status}")

    @classmethod
    def log_container_status(cls, container_id: str, status: str, details: Optional[str] = None):
        """
        Log container status

        Args:
            container_id: Container identifier
            status: Current status
            details: Additional status details
        """
        logger = cls.get_logger('containers')
        msg = f"Container {container_id}: {status}"
        if details:
            msg += f" - {details}"
        logger.info(msg)

    @classmethod
    def log_error_with_context(cls,
                              logger_name: str,
                              error: Exception,
                              context: Optional[Dict[str, Any]] = None):
        """
        Log error with additional context

        Args:
            logger_name: Name of logger to use
            error: Exception that occurred
            context: Additional context information
        """
        logger = cls.get_logger(logger_name)

        msg = f"Error: {str(error)}"
        if context:
            context_str = ", ".join(f"{k}={v}" for k, v in context.items())
            msg += f" (Context: {context_str})"

        logger.error(msg, exc_info=True)

class PerformanceTimer:
    """
    Context manager for timing operations
    """

    def __init__(self, operation_name: str, logger_name: str = 'performance'):
        self.operation_name = operation_name
        self.logger_name = logger_name
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = time.time()
        logger = get_logger(self.logger_name)
        logger.debug(f"Starting operation: {self.operation_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        duration = self.end_time - self.start_time

        logger = get_logger(self.logger_name)

        if exc_type is not None:
            logger.error(f"Operation '{self.operation_name}' failed after {duration:.3f}s: {exc_val}")
        else:
            logger.info(f"Operation '{self.operation_name}' completed in {duration:.3f}s")

    def get_duration(self) -> Optional[float]:
        """Get duration if timing is complete"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None

class LogBuffer:
    """
    Buffer for collecting logs to display in UI
    """

    def __init__(self, max_lines: int = 1000):
        self.max_lines = max_lines
        self.lines = []
        self.handler = None

    def setup_handler(self, logger_name: str = None):
        """Setup handler to capture logs"""
        self.handler = LogBufferHandler(self)

        if logger_name:
            logger = get_logger(logger_name)
            logger.addHandler(self.handler)
        else:
            # Add to root logger to capture all logs
            logging.getLogger().addHandler(self.handler)

    def add_line(self, timestamp: datetime, level: str, message: str):
        """Add line to buffer"""
        self.lines.append({
            'timestamp': timestamp,
            'level': level,
            'message': message
        })

        # Keep buffer size manageable
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def get_recent_lines(self, count: int = 50) -> list:
        """Get recent log lines"""
        return self.lines[-count:]

    def clear(self):
        """Clear buffer"""
        self.lines.clear()

    def cleanup(self):
        """Remove handler"""
        if self.handler:
            logging.getLogger().removeHandler(self.handler)

class LogBufferHandler(logging.Handler):
    """Handler that captures logs to buffer"""

    def __init__(self, log_buffer: LogBuffer):
        super().__init__()
        self.log_buffer = log_buffer

    def emit(self, record):
        """Emit record to buffer"""
        try:
            timestamp = datetime.fromtimestamp(record.created)
            self.log_buffer.add_line(
                timestamp=timestamp,
                level=record.levelname,
                message=record.getMessage()
            )
        except Exception:
            self.handleError(record)

# Convenience function for getting loggers
def get_logger(name: str) -> logging.Logger:
    """
    Convenience function to get logger

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return DistributedRenderLogger.get_logger(name)

# Initialize logging on module import
def initialize_logging():
    """Initialize logging system with Blender preferences"""
    try:
        # Try to get preferences for debug mode
        debug_mode = False
        log_file = None

        if hasattr(bpy.context, 'preferences'):
            addon_prefs = bpy.context.preferences.addons.get(__package__.split('.')[0])
            if addon_prefs and hasattr(addon_prefs.preferences, 'debug_mode'):
                debug_mode = addon_prefs.preferences.debug_mode

                # Setup log file if debug mode is enabled
                if debug_mode:
                    temp_dir = Path(bpy.path.abspath("//")) / "distributed_render_logs"
                    temp_dir.mkdir(exist_ok=True)
                    log_file = temp_dir / f"render_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        DistributedRenderLogger.setup_logging(
            log_file=log_file,
            debug_mode=debug_mode
        )

    except Exception as e:
        # Fallback basic logging if Blender context not available
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        print(f"Warning: Could not setup advanced logging: {e}")

# Initialize when module loads
initialize_logging()