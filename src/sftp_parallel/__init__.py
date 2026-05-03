"""sftp_parallel - Parallel SFTP uploader with verification."""

from sftp_parallel.lib import (
    validate_host,
    validate_port,
    validate_remote_dir,
    validate_filename,
    compute_local_checksum,
    compute_remote_checksums,
    verify_uploads,
    get_remote_file_sizes,
    filter_existing_files,
    run_sftp,
)
from sftp_parallel.upload import parallel_upload

try:
    from importlib.metadata import version as _version

    __version__ = _version("sftp-parallel")
except Exception:
    __version__ = "0.0.0"

__all__ = [
    "__version__",
    "parallel_upload",
    "get_remote_file_sizes",
    "filter_existing_files",
    "run_sftp",
    "verify_uploads",
    "compute_local_checksum",
    "compute_remote_checksums",
    "validate_host",
    "validate_port",
    "validate_remote_dir",
    "validate_filename",
]
