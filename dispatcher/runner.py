import subprocess


class SubprocessRunner:
    def run(self, *command):
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
