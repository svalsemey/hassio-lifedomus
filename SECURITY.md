# Security Policy

- Do not open issues with secrets or personal data.
- If you discover a vulnerability, please open a private security advisory or contact the maintainer.
- Credentials and alarm codes are stored by Home Assistant in the config entry. Consider using strong local network security.
- Diagnostics files redact the password, the alarm code and the site and user keys, including inside raw gateway responses. Review the file before attaching it to a public issue.