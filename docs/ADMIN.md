# Administrator notes

The most important operational distinction is between installation-time Compose commands and runtime Docker lifecycle control.

- Compose creates and configures engine containers.
- Dispatcher starts and stops those existing containers.
- Gateway never receives Docker socket access.

When changing a compose file, recreate that engine container before expecting the Dispatcher to use the new configuration.
