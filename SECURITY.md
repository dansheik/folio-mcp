# Security

Use GitHub private vulnerability reporting. Do not include API keys, invoices or
bank data in public issues. Only synthetic fixtures belong in this repository.

Supported version: 0.1.x pilot for macOS. Credentials use Apple Keychain with no
plaintext fallback. Each profile has private local proposal files and an invoice
snapshot. Expiry invalidates approval but does not delete local files; use `purge`.

The only remote mutation is a separately approved attachment upload to an event.
There are no payment, category-editing, completion or deletion tools. Approval is
single-use, content-bound and expires after ten minutes. It is a human control step,
not protection against another process already running with the user's privileges.

Do not blindly retry ambiguous uploads. Check Folio manually before clearing local
history. Revocation is done in Folio; local logout only deletes the stored key.
