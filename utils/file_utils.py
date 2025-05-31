"""
File utilities for distributed rendering
Handles file operations, path management, and file system tasks
"""

import os
import shutil
import hashlib
from pathlib import Path
from typing import List, Optional, Union
import tempfile
import time

class FileUtils:
    """
    Utility class for file operations
    """

    @staticmethod
    def ensure_directory(path: Union[str, Path]) -> Path:
        """
        Ensure directory exists, create if necessary

        Args:
            path: Directory path to ensure

        Returns:
            Path object of the directory
        """
        path_obj = Path(path)
        path_obj.mkdir(parents=True, exist_ok=True)
        return path_obj

    @staticmethod
    def clear_directory(path: Union[str, Path]) -> None:
        """
        Clear all contents of a directory

        Args:
            path: Directory path to clear
        """
        path_obj = Path(path)
        if path_obj.exists() and path_obj.is_dir():
            for item in path_obj.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    @staticmethod
    def copy_file_safe(source: Union[str, Path], destination: Union[str, Path]) -> bool:
        """
        Safely copy file with error handling

        Args:
            source: Source file path
            destination: Destination file path

        Returns:
            True if successful, False otherwise
        """
        try:
            source_path = Path(source)
            dest_path = Path(destination)

            # Ensure destination directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy file
            shutil.copy2(source_path, dest_path)
            return True

        except Exception as e:
            print(f"Error copying file {source} to {destination}: {e}")
            return False

    @staticmethod
    def get_unique_filename(directory: Union[str, Path], filename: str) -> str:
        """
        Get unique filename in directory (add suffix if file exists)

        Args:
            directory: Target directory
            filename: Desired filename

        Returns:
            Unique filename that doesn't exist in directory
        """
        dir_path = Path(directory)
        file_path = dir_path / filename

        if not file_path.exists():
            return filename

        # Split filename and extension
        name_part = Path(filename).stem
        ext_part = Path(filename).suffix

        # Find unique name
        counter = 1
        while file_path.exists():
            new_filename = f"{name_part}_{counter:03d}{ext_part}"
            file_path = dir_path / new_filename
            counter += 1

        return file_path.name

    @staticmethod
    def get_file_hash(file_path: Union[str, Path], algorithm: str = 'md5') -> str:
        """
        Calculate hash of file

        Args:
            file_path: Path to file
            algorithm: Hash algorithm ('md5', 'sha1', 'sha256')

        Returns:
            Hex digest of file hash
        """
        hash_func = hashlib.new(algorithm)

        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hash_func.update(chunk)

        return hash_func.hexdigest()

    @staticmethod
    def get_directory_size(path: Union[str, Path]) -> int:
        """
        Get total size of directory in bytes

        Args:
            path: Directory path

        Returns:
            Total size in bytes
        """
        total_size = 0
        path_obj = Path(path)

        if path_obj.exists() and path_obj.is_dir():
            for file_path in path_obj.rglob('*'):
                if file_path.is_file():
                    total_size += file_path.stat().st_size

        return total_size

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """
        Format file size in human readable format

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted size string (e.g., "1.5 MB")
        """
        if size_bytes == 0:
            return "0 B"

        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_index = 0
        size = float(size_bytes)

        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1

        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        else:
            return f"{size:.1f} {units[unit_index]}"

    @staticmethod
    def find_files_by_extension(directory: Union[str, Path],
                               extensions: List[str],
                               recursive: bool = True) -> List[Path]:
        """
        Find files with specific extensions in directory

        Args:
            directory: Directory to search
            extensions: List of extensions (e.g., ['.blend', '.jpg'])
            recursive: Search recursively in subdirectories

        Returns:
            List of matching file paths
        """
        dir_path = Path(directory)
        extensions_lower = [ext.lower() for ext in extensions]
        found_files = []

        if not dir_path.exists():
            return found_files

        search_pattern = '**/*' if recursive else '*'

        for file_path in dir_path.glob(search_pattern):
            if file_path.is_file() and file_path.suffix.lower() in extensions_lower:
                found_files.append(file_path)

        return found_files

    @staticmethod
    def create_temp_directory(prefix: str = 'dist_render_') -> Path:
        """
        Create temporary directory

        Args:
            prefix: Prefix for temporary directory name

        Returns:
            Path to created temporary directory
        """
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        return temp_dir

    @staticmethod
    def cleanup_old_files(directory: Union[str, Path],
                         max_age_hours: int = 24,
                         pattern: str = '*') -> int:
        """
        Clean up old files in directory

        Args:
            directory: Directory to clean
            max_age_hours: Maximum age of files in hours
            pattern: File pattern to match

        Returns:
            Number of files deleted
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            return 0

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        deleted_count = 0

        for file_path in dir_path.glob(pattern):
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                    except Exception as e:
                        print(f"Error deleting old file {file_path}: {e}")

        return deleted_count

    @staticmethod
    def safe_filename(filename: str) -> str:
        """
        Make filename safe for filesystem

        Args:
            filename: Original filename

        Returns:
            Safe filename with invalid characters removed/replaced
        """
        # Characters not allowed in filenames
        invalid_chars = '<>:"/\\|?*'

        # Replace invalid characters with underscore
        safe_name = filename
        for char in invalid_chars:
            safe_name = safe_name.replace(char, '_')

        # Remove multiple consecutive underscores
        while '__' in safe_name:
            safe_name = safe_name.replace('__', '_')

        # Strip leading/trailing underscores and whitespace
        safe_name = safe_name.strip('_ ')

        # Ensure filename is not empty
        if not safe_name:
            safe_name = 'unnamed_file'

        return safe_name

    @staticmethod
    def get_relative_path(file_path: Union[str, Path], base_path: Union[str, Path]) -> str:
        """
        Get relative path from base path

        Args:
            file_path: Target file path
            base_path: Base directory path

        Returns:
            Relative path string
        """
        try:
            file_path_obj = Path(file_path).resolve()
            base_path_obj = Path(base_path).resolve()
            return str(file_path_obj.relative_to(base_path_obj))
        except ValueError:
            # If paths are not relative, return absolute path
            return str(Path(file_path).resolve())

    @staticmethod
    def ensure_file_extension(filename: str, extension: str) -> str:
        """
        Ensure filename has specific extension

        Args:
            filename: Original filename
            extension: Desired extension (with or without dot)

        Returns:
            Filename with correct extension
        """
        if not extension.startswith('.'):
            extension = '.' + extension

        file_path = Path(filename)
        if file_path.suffix.lower() != extension.lower():
            return str(file_path.with_suffix(extension))

        return filename

    @staticmethod
    def backup_file(file_path: Union[str, Path], backup_suffix: str = '.bak') -> Optional[Path]:
        """
        Create backup of file

        Args:
            file_path: Path to file to backup
            backup_suffix: Suffix for backup file

        Returns:
            Path to backup file, or None if failed
        """
        try:
            source_path = Path(file_path)
            if not source_path.exists():
                return None

            backup_path = source_path.with_suffix(source_path.suffix + backup_suffix)

            # If backup already exists, add timestamp
            if backup_path.exists():
                timestamp = int(time.time())
                backup_path = source_path.with_suffix(f"{source_path.suffix}.{timestamp}{backup_suffix}")

            shutil.copy2(source_path, backup_path)
            return backup_path

        except Exception as e:
            print(f"Error creating backup of {file_path}: {e}")
            return None

    @staticmethod
    def is_file_locked(file_path: Union[str, Path]) -> bool:
        """
        Check if file is locked (being used by another process)

        Args:
            file_path: Path to file to check

        Returns:
            True if file appears to be locked
        """
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                return False

            # Try to open file in write mode
            with open(file_path_obj, 'a'):
                pass
            return False

        except (PermissionError, OSError):
            return True

    @staticmethod
    def wait_for_file(file_path: Union[str, Path],
                     timeout: int = 30,
                     check_interval: float = 0.5) -> bool:
        """
        Wait for file to exist and be ready

        Args:
            file_path: Path to file to wait for
            timeout: Maximum time to wait in seconds
            check_interval: How often to check in seconds

        Returns:
            True if file is ready, False if timeout
        """
        file_path_obj = Path(file_path)
        start_time = time.time()

        while time.time() - start_time < timeout:
            if file_path_obj.exists() and not FileUtils.is_file_locked(file_path_obj):
                # Additional check: file size should be stable
                if file_path_obj.stat().st_size > 0:
                    initial_size = file_path_obj.stat().st_size
                    time.sleep(0.1)  # Brief pause

                    if file_path_obj.stat().st_size == initial_size:
                        return True

            time.sleep(check_interval)

        return False

class PathManager:
    """
    Manages paths for distributed render operations
    """

    def __init__(self, base_path: Union[str, Path]):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def get_bucket_path(self, bucket_id: int) -> Path:
        """Get path for bucket files"""
        bucket_dir = self.base_path / f"bucket_{bucket_id:04d}"
        bucket_dir.mkdir(exist_ok=True)
        return bucket_dir

    def get_container_path(self, container_id: str) -> Path:
        """Get path for container files"""
        container_dir = self.base_path / f"container_{container_id}"
        container_dir.mkdir(exist_ok=True)
        return container_dir

    def get_output_path(self, filename: str) -> Path:
        """Get path for output files"""
        output_dir = self.base_path / "output"
        output_dir.mkdir(exist_ok=True)
        return output_dir / filename

    def get_temp_path(self, filename: str) -> Path:
        """Get path for temporary files"""
        temp_dir = self.base_path / "temp"
        temp_dir.mkdir(exist_ok=True)
        return temp_dir / filename

    def cleanup_all(self):
        """Clean up all managed paths"""
        if self.base_path.exists():
            shutil.rmtree(self.base_path)