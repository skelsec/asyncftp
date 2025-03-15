![Supported Python versions](https://img.shields.io/badge/python-3.8+-blue.svg) [![Twitter](https://img.shields.io/twitter/follow/skelsec?label=skelsec&style=social)](https://twitter.com/intent/follow?screen_name=skelsec)

## :triangular_flag_on_post: Sponsors

If you like this project, consider purchasing licenses of [OctoPwn](https://octopwn.com/), our full pentesting suite that runs in your browser!  
For notifications on new builds/releases and other info, hop on to our [Discord](https://discord.gg/PM8utcNxMS)


# asyncftp
Fully asynchronous FTP client library for Python.

## :triangular_flag_on_post: Runs in the browser

This project, alongside with many other pentester tools runs in the browser with the power of OctoPwn!  
Check out the community version at [OctoPwn - Live](https://live.octopwn.com/)

# Features
Currently only basic FTP features are implemented.

- [x] Connect to FTP server
- [x] Login to FTP server
- [x] List directory
- [x] Get file
- [x] Put file
- [x] Delete file
- [x] Create directory
- [x] Remove directory
- [x] Rename file
- [x] Change working directory
- [x] Get current working directory
- [x] Get file size
- [x] Get file modification time
- [ ] Active mode
- [ ] SSL/TLS
- [ ] FTPES


# Installation
```bash
pip install asyncftp
```

# Usage
```bash
asyncftp-client 'ftp+plain-password://myuser:change_this_password@127.0.0.1:2121' login list help feat stat "cwd ../" cdup "pwd" "size file.txt" "get file.txt" "put test.txt"
```

# License
MIT