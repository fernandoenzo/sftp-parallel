from typing import List


def sftp_escape(path: str) -> str:
    escaped = path.replace("\\", "\\\\")
    return escaped.replace('"', '\\"')


def build_batch_commands(remote_dir: str, local_dir: str, files: List[str]) -> str:
    commands: List[str] = []
    commands.append(f'cd "{sftp_escape(remote_dir)}"')

    for file in files:
        escaped_local = sftp_escape(f"{local_dir}/{file}")
        commands.append(f'put -f "{escaped_local}"')

    commands.append("bye")
    return "\n".join(commands)
