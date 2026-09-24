import subprocess


class CommandError(RuntimeError):
    def __init__(self, message, *, command, returncode=None, stderr=""):
        super().__init__(message)
        self.command = tuple(command)
        self.returncode = returncode
        self.stderr = stderr


class CommandTimeout(CommandError):
    pass


class CommandFailed(CommandError):
    pass


class SubprocessRunner:
    def run(self, *command, timeout=None):
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CommandTimeout(
                f"command timed out after {timeout}s: {' '.join(command)}",
                command=command,
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise CommandFailed(
                f"command failed ({exc.returncode}): {' '.join(command)}",
                command=command,
                returncode=exc.returncode,
                stderr=exc.stderr or "",
            ) from exc
        return result.stdout
