import copy
from urllib.parse import urlparse, parse_qs
from typing import List
from asysocks.unicomm.utils.paramprocessor import str_one, int_one, bool_one

from asysocks.unicomm.common.target import UniTarget, UniProto
from asysocks.unicomm.common.proxy import UniProxyProto, UniProxyTarget

ftp_target_url_params = {
	'passive' : bool_one,
}

class FTPTarget(UniTarget):
    def __init__(self, ip: str, port: int = 21, protocol: UniProto = UniProto.CLIENT_TCP, timeout: int = 10, hostname: str = None, proxies: List[UniProxyTarget] = None, domain: str = None, dc_ip: str = None, dns: str = None, passive: bool = True):
        UniTarget.__init__(self, ip, port, protocol, timeout, hostname = hostname, proxies = proxies, domain = domain, dc_ip = dc_ip, dns=dns)
        self.passive: bool = passive

    @staticmethod
    def from_url(url:str):
        url_e = urlparse(url)
        schemes = url_e.scheme.upper().split('+')

        # TODO: add proper protocol support
        # ftp+ssl://
        ftpproto = 'FTP'
        if len(schemes) == 2 and schemes[0] == 'FTP' and schemes[1] == 'SSL':
            ftpproto = 'FTPS'
        # ftp://
        elif len(schemes) == 1 and schemes[0] == 'FTP':
            ftpproto = 'FTP'

        port = 21
        if url_e.port:
            port = url_e.port

        unitarget, extraparams = UniTarget.from_url(url, UniProto.CLIENT_TCP, port, ftp_target_url_params)
        target = FTPTarget(
            ip = unitarget.ip,
            port = unitarget.port,
            protocol = unitarget.protocol,
            timeout = unitarget.timeout,
            hostname = unitarget.hostname,
            proxies = unitarget.proxies,
            domain = unitarget.domain,
            dc_ip = unitarget.dc_ip,
            dns = unitarget.dns,
            passive = extraparams.get('passive', True))
        return target
