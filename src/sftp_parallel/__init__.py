"""sftp_parallel - Parallel SFTP uploader with verification."""

from sftp_parallel.batch import (
    validate_host,
    validate_port,
    validate_remote_dir,
    validate_filename,
)
from sftp_parallel.uploader import (
    upload_files,
    get_remote_file_sizes,
    filter_existing_files,
)
from sftp_parallel.verify import (
    verify_uploads,
    compute_local_checksum,
    compute_remote_checksums,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "upload_files",
    "get_remote_file_sizes",
    "filter_existing_files",
    "verify_uploads",
    "compute_local_checksum",
    "compute_remote_checksums",
    "validate_host",
    "validate_port",
    "validate_remote_dir",
    "validate_filename",
]
