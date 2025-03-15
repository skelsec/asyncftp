import copy
import ipaddress
from asyncftp.common.target import FTPTarget
from asyauth.common.credentials import UniCredential
from asyncftp.connection import FTPClientConnection

class FTPConnectionFactory:
    def __init__(self, target:FTPTarget, credential:UniCredential):
        self.target = target
        self.credential = credential

    def get_target(self):
        return copy.deepcopy(self.target)

    def get_credential(self):
        return copy.deepcopy(self.credential)

    def get_connection(self):
        return FTPClientConnection(self.get_target(), self.get_credential())

    def create_connection_newtarget(self, ip_or_hostname, port:int=None):
        credential = self.get_credential()
        target = copy.deepcopy(self.target)
        try:
            ipaddress.ip_address(ip_or_hostname)
            target.ip = ip_or_hostname
            target.hostname = None
        except:
            target.hostname = ip_or_hostname
            target.ip = ip_or_hostname
        if port is not None:
            target.port = port
        return FTPClientConnection(target, credential)

    @staticmethod
    def from_url(url:str):
        target = FTPTarget.from_url(url)
        credential = UniCredential.from_url(url)
        return FTPConnectionFactory(target, credential)
