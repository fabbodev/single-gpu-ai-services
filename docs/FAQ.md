# FAQ

## Is this a one-click installer?

No. The manual installation steps are intentionally visible and documented.

## Does it require an RTX 3080?

No, but the reference deployment and OCR memory tuning were validated on an RTX 3080 10 GB.

## Can two GPU engines run at once?

Not through the current Dispatcher. It grants one logical GPU lease at a time.

## Is MCP required?

No. REST/OpenAPI is the core interface; MCP can be added externally.

## Why does the Dispatcher need the Docker socket?

It starts, inspects, and stops pre-created engine containers. That is also why it must remain a trusted internal component.

## Are models included?

No. Model weights are deliberately excluded from Git.
