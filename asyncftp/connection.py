import asyncio
import traceback
import re
import copy
import io
import os
from pathlib import Path
import datetime
from typing import List, Tuple, Awaitable, Coroutine, Any, AsyncGenerator
from asyncftp.common.target import FTPTarget
from asyauth.common.credentials import UniCredential
from asyauth.common.constants import asyauthSecret
from asysocks.unicomm.client import UniClient
from asyncftp.network.packetizer import FTPPacketizer
from asysocks.unicomm.common.packetizers import Packetizer
from asyncftp.common.exceptions import FTPException, FTPResponseException, \
    FTPResponseExpectationException, FTPCommandException, FTPAuthenticationException

class FTPResponse:
    def __init__(self, code: str, messages: List[str]):
        self.code = code
        self.messages = messages
    
    def expect(self, expect: List[str]):
        if self.code in expect:
            return True
        if self.code[0] == "5":
            raise FTPResponseException(self.code, self.messages)
        raise FTPResponseExpectationException(self.code, self.messages, expect)

    def more_messages(self):
        if self.code[0] == "1":
            return True
        return False

    def __str__(self):
        if len(self.messages) == 0:
            return self.code
        if len(self.messages) == 1:
            return f"{self.code} {self.messages[0]}"
        if len(self.messages) > 1:
            res = []
            res.append(self.code + "-" + self.messages[0])
            for m in self.messages[1:-1]:
                res.append(m)
            res.append(self.code + " " + self.messages[-1])
            return "\r\n".join(res)

def parse_mlsd_line(line: str, basepath: str = ''):
    entry = {}
    line = line.strip()
    parts, fname = line.split("; ")
    entry['name'] = fname
    entry['fullpath'] = os.path.join(basepath, fname) # TODO: check if this is correct bc windows might not like it
    entry['size'] = 0
    parts = parts.split(";")
    for part in parts:
        key, value = part.split("=")
        if key == 'modify':
            value = datetime.datetime.strptime(value, "%Y%m%d%H%M%S")
        elif key == 'size':
            value = int(value)
        entry[key] = value
    return entry


class FTPClientConnection:
    def __init__(self, target: FTPTarget, credential: UniCredential):
        self.target = target
        self.credential = credential
        self.connection_closed_evt = asyncio.Event()
        self.network_connection = None
        self.banner = []
        self.encoding = 'utf-8'
        self.__lock = asyncio.Lock()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.disconnect()

    async def __read_data_channel(self, line_based: bool = False):
        data_connection = None
        buffer = b''
        try:
            if self.target.passive is False:
                raise Exception("Active mode not supported")
            target, err = await self.__pasv()
            if err is not None:
                raise err
            client = UniClient(target, Packetizer())
            data_connection = await client.connect()
            async for data in data_connection.read():
                if line_based is True:
                    buffer += data
                    while True:
                        m = buffer.find(b"\n")
                        if m == -1:
                            break
                        temp = buffer[:m]
                        buffer = buffer[m+1:]
                        yield temp, None
                        
                else:
                    yield data, None
        
        except Exception as e:
            yield None, e
        finally:
            if data_connection is not None:
                await data_connection.close()

    async def __write_data_channel(self, data: io.BytesIO, chunksize: int = 102400):
        data_connection = None
        try:
            if self.target.passive is False:
                raise Exception("Active mode not supported")
            target, err = await self.__pasv()
            if err is not None:
                raise err
            client = UniClient(target, Packetizer())
            data_connection = await client.connect()
            while True:
                chunk = data.read(chunksize)
                if len(chunk) == 0:
                    break
                await data_connection.write(chunk)
        except Exception as e:
            yield None, e
        finally:
            if data_connection is not None:
                await data_connection.close()

    
    async def __read_response(self):
        """
        Read the response from the server.
        If as_list is True, the response is returned as a list of strings.
        Otherwise, the response is returned as a single string.
        """
        try:
            rcode = None
            response = []
            while True:
                res = await self.network_connection.read_one()
                if res is None:
                    break
                line = res
                if rcode is None:
                    to_continue = line[3] == '-'
                    rcode = line[:3]
                    line = line[4:].strip()
                    response.append(line)
                    if to_continue is False:
                        break
                    continue
                if line.startswith(rcode + ' '):
                    response.append(line[len(rcode) + 1:].strip())
                    break
                else:
                    response.append(line)
            return FTPResponse(rcode, response), None
        except Exception as e:
            return None, e

    def connection_lock_asynciter(func):
        async def wrapper(self, *args, **kwargs):
            async with self.__lock:
                async for result in func(self, *args, **kwargs):
                    yield result
        return wrapper

    def connection_lock(func):
        async def wrapper(self, *args, **kwargs):
            async with self.__lock:
                return await func(self, *args, **kwargs)
        return wrapper

    async def connect(self, nologin: bool = False) -> Awaitable[Tuple[bool, Exception]]:
        """
        Connect to the FTP server. Perform the handshake and login if needed.
        Returns a tuple of (success, error).
        """
        try:
            self.connection_closed_evt = asyncio.Event()
            packetizer = FTPPacketizer()
            client = UniClient(self.target, packetizer)
            self.network_connection = await client.connect()
            response = None
            for _ in range(255):
                # read the response
                response, err = await self.__read_response()
                if err is not None:
                    raise err
                if response.more_messages():
                    continue
                if response.expect(["220", "230", "232"]):
                    if response.code == "220":
                        self.banner = response.messages
                    break
            if response is None:
                raise FTPException("No response from server")
            if nologin is True:
                return True, None
            if response.code in ["230", "232"]:
                # 230 would be weird, 232 means logged in via SSL
                return True, None
            else:
                return await self.login()
        except Exception as e:
            await self.disconnect()
            return False, e

    async def disconnect(self):
        """
        Disconnect from the FTP server.
        Call this when you are done with the connection.
        """
        if self.network_connection is not None:
            try:
                await self.__quit()
            except Exception as e:
                pass
            await self.network_connection.close()
            self.network_connection = None
            self.connection_closed_evt.set()

    async def login(self) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Login to the FTP server. Only call this if you called connect with nologin=False.
        Returns a tuple of (success, error).
        """
        try:
            if self.credential.stype == asyauthSecret.NONE:
                await self.network_connection.write(b"USER anonymous\r\n")
                response, err = await self.__read_response()
                if err is not None:
                    raise err
                response.expect(["331", "332"])
                if response.code == "331":
                    await self.network_connection.write(b"PASS anonymous@\r\n")
                    response, err = await self.__read_response()
                    if err is not None:
                        raise err
                    response.expect(["230"])
                    return True, None
                else:
                    return False, FTPAuthenticationException(response.code, response.messages)
            elif self.credential.stype == asyauthSecret.PASSWORD:
                return await self.login_plain()
            else:
                raise Exception("Unsupported credential type %s" % self.credential.stype)

        except Exception as e:
            return False, e
        return True, None

    async def login_anonymous(self) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Login to the FTP server as anonymous. Only call this if you called connect with nologin=False.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"USER anonymous\r\n")
            await self.network_connection.write(b"PASS anonymous@\r\n")
        except Exception as e:
            return False, e

    async def login_plain(self) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Login to the FTP server using a username and password. Only call this if you called connect with nologin=False.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"USER %s\r\n" % self.credential.username.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["331", "332"])
            if response.code == "331":
                await self.network_connection.write(b"PASS %s\r\n" % self.credential.secret.encode())
                response, err = await self.__read_response()
                if err is not None:
                    raise err
                if response.code == "230":
                    return True, None
                else:
                    return False, FTPAuthenticationException(response.code, response.messages)
            else:
                return False, FTPAuthenticationException(response.code, response.messages)
        except Exception as e:
            return False, e
        return True, None

    @connection_lock_asynciter
    async def list(self, path: str = '') -> AsyncGenerator[Tuple[str, Exception], None]:
        """
        List the contents of a directory on the FTP server.
        Returns a generator of (data, error).
        """
        try:
            if path == '':
                await self.network_connection.write(b"LIST\r\n")
            else:
                await self.network_connection.write(b"LIST %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["150"])
            async for data, err in self.__read_data_channel(line_based=True):
                if err is not None:
                    raise err
                yield data.decode(self.encoding), None
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["226"])
        except Exception as e:
            yield None, e
        
    @connection_lock_asynciter
    async def feat(self) -> AsyncGenerator[Tuple[str, Exception], None]:
        """
        Get the features of the FTP server.
        Returns a generator of features.
        """
        try:
            await self.network_connection.write(b"FEAT\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["211", "214"])
            for feat in response.messages:
                yield feat, None
        except Exception as e:
            yield None, e

    @connection_lock_asynciter
    async def help(self, command: str = '') -> AsyncGenerator[Tuple[str, Exception], None]:
        """
        Get the help of the FTP server.
        Returns a generator of help messages.
        """
        try:
            if command == '':
                await self.network_connection.write(b"HELP\r\n")
            else:
                await self.network_connection.write(b"HELP %s\r\n" % command.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["214", "226"])
            for help in response.messages:
                yield help, None
        except Exception as e:
            yield None, e

    @connection_lock_asynciter
    async def stat(self) -> AsyncGenerator[Tuple[str, Exception], None]:
        """
        Get the status of the FTP server.
        Returns a generator of status messages.
        """
        try:
            await self.network_connection.write(b"STAT\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["211"])
            for stat in response.messages:
                yield stat, None
        except Exception as e:
            yield None, e

    @connection_lock
    async def cwd(self, path: str) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Change the working directory of the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"CWD %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["250"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def cdup(self) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Change the working directory of the FTP server to the parent directory.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"CDUP\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["200", "250"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def pwd(self) -> Coroutine[Any, Any, Tuple[str, Exception]]:
        """
        Get the current working directory of the FTP server.
        Returns a tuple of (directory_path, error).
        """
        try:
            await self.network_connection.write(b"PWD\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["257"])
            
            # Extract the path from the response
            # The path is typically enclosed in quotes
            path_match = re.search(r'"(.*?)"', response.messages[0])
            if path_match:
                return path_match.group(1), None
            else:
                # Fallback if quotes aren't found
                return response.messages[0], None
        except Exception as e:
            return None, e
    
    
    async def __size(self, path: str) -> Coroutine[Any, Any, Tuple[int, Exception]]:
        """
        Get the size of a file on the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            await self.__type("I")
            await self.network_connection.write(b"SIZE %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["213"])
            return int(response.messages[0]), None
        except Exception as e:
            return None, e

    @connection_lock
    async def size(self, path: str) -> Coroutine[Any, Any, Tuple[int, Exception]]:
        """
        Get the size of a file on the FTP server.
        Returns a tuple of (success, error).
        """
        return await self.__size(path)

    async def __type(self, type: str) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Set the type of the data connection.
        type: A, I, E, L for ASCII, Image, EBCDIC, Local
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"TYPE %s\r\n" % type.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["200"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def type(self, type: str) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Set the type of the data connection.
        type: A, I, E, L for ASCII, Image, EBCDIC, Local
        Returns a tuple of (success, error).
        """
        return await self.__type(type)

    async def __pasv(self) -> Coroutine[Any, Any, Tuple[FTPTarget, Exception]]:
        """
        Get the passive target of the FTP server.
        Returns a tuple of (target, error).
        """
        try:
            await self.network_connection.write(b"PASV\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["227"])
            # regex to extract the port from the response
            passive_def = re.search(r'\((.*?)\)', response.messages[0]).group(1)
            if passive_def is None:
                raise FTPCommandException("PASV", response.code, response.messages)
            passive_ip = '.'.join(passive_def.split(",")[:4])
            passive_port = int(passive_def.split(",")[4]) * 256 + int(passive_def.split(",")[5])
            return FTPTarget(ip=passive_ip, port=passive_port, proxies=copy.deepcopy(self.target.proxies)), None
        except Exception as e:
            return None, e

    @connection_lock
    async def pasv(self) -> Coroutine[Any, Any, Tuple[FTPTarget, Exception]]:
        """
        Get the passive target of the FTP server.
        Returns a tuple of (target, error).
        """
        return await self.__pasv()

    @connection_lock
    async def get(self, path: str, dstpath: str = None) -> Coroutine[Any, Any, Tuple[str, Exception]]:
        """
        Get a file from the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            if dstpath is None:
                dstpath = str(Path(path).name)
            await self.network_connection.write(b"RETR %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["150"])
            with open(dstpath, "wb") as f:
                async for data, err in self.__read_data_channel(line_based=False):
                    if err is not None:
                        raise err
                    f.write(data)
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["226"])
            return dstpath, None
        except Exception as e:
            return None, e

    @connection_lock_asynciter
    async def get_file(self, path: str) -> AsyncGenerator[Tuple[bytes, Exception], None]:
        """
        Get a file from the FTP server.
        Returns a generator of (data, error).
        """
        try:
            await self.network_connection.write(b"RETR %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["150"])
            async for data, err in self.__read_data_channel(line_based=False):
                if err is not None:
                    raise err
                yield data, None
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["226"])
        except Exception as e:
            yield None, e

    @connection_lock
    async def mdtm(self, path: str) -> Coroutine[Any, Any, Tuple[datetime.datetime, Exception]]:
        """
        Get the modification time of a file on the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"MDTM %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["213"])
            mdtm = response.messages[0].decode(self.encoding)
            date = datetime.datetime.strptime(mdtm, "%Y%m%d%H%M%S")
            return date, None
        except Exception as e:
            return None, e

    @connection_lock_asynciter
    async def mlsd(self, path: str = '') -> AsyncGenerator[Tuple[str, dict, Exception], None]:
        """
        Lists the contents of a directory in a standardized machine-readable format.
        Returns a tuple of (success, error).
        """
        try:
            if path == '':
                await self.network_connection.write(b"MLSD\r\n")
            else:
                await self.network_connection.write(b"MLSD %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["150"])
            async for data, err in self.__read_data_channel(line_based=True):
                if err is not None:
                    raise err
                data = data.decode(self.encoding)
                for line in data.split("\r\n"):
                    #parse the line
                    if line == '':
                        continue
                    entry = parse_mlsd_line(line, path)
                    yield entry['name'], entry, None
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["226"])
        except Exception as e:
            yield None, None, e

    @connection_lock
    async def mlst(self, path: str) -> Coroutine[Any, Any, Tuple[str, dict, Exception]]:
        """
        Provides data about exactly the object named on its command line in a standardized machine-readable format.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"MLST %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["250"])
            entry = parse_mlsd_line(response.messages[1])
            return entry['name'], entry, None
        except Exception as e:
            return None, None, e

    @connection_lock
    async def mkd(self, path: str) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Create a directory on the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"MKD %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["257"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def rmd(self, path: str) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Remove a directory on the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"RMD %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["250"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def noop(self) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        No operation.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"NOOP\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["200"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def acct(self) -> Coroutine[Any, Any, Tuple[str, Exception]]:
        """
        Get the account information of the FTP server.
        Returns a tuple of (string, error).
        """
        try:
            await self.network_connection.write(b"ACCT\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["200"])
            return response.messages, None # TODO: check if this is correct
        except Exception as e:
            return None, e
    
    @connection_lock
    async def site(self, command: str) -> Coroutine[Any, Any, Tuple[str, Exception]]:
        """
        Execute a SITE command on the FTP server.
        Returns a tuple of (string, error).
        """
        try:
            await self.network_connection.write(b"SITE %s\r\n" % command.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["214"])
            return response.messages[0], None
        except Exception as e:
            return None, e

    @connection_lock
    async def rawcmd(self, command: str) -> Coroutine[Any, Any, Tuple[FTPResponse, Exception]]:
        """
        Execute a raw command on the FTP server.
        Returns a tuple of (FTPResponse, error).
        """
        try:
            await self.network_connection.write(b"%s\r\n" % command.encode())
            return await self.__read_response()
        except Exception as e:
            return None, e

    @connection_lock
    async def stor(self, path: str, data: io.BytesIO = None) -> AsyncGenerator[Tuple[str, Exception], None]:
        """
        Store a file on the FTP server.
        Returns a tuple of (string, error).
        """
        try:
            await self.network_connection.write(b"STOR %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                    raise err
            response.expect(["150"])
            if data is not None:
                async for data, err in self.__write_data_channel(data):
                    if err is not None:
                        raise err
            else:
                with open(path, "rb") as f:
                    async for data, err in self.__write_data_channel(f):
                        if err is not None:
                            raise err
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["226"])
            return path, None
        except Exception as e:
            return None, e
    
    @connection_lock
    async def appe(self, path: str, data: io.BytesIO = None) -> AsyncGenerator[Tuple[str, Exception], None]:
        """
        Append (+create) a file on the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            if isinstance(data, bytes):
                data = io.BytesIO(data)
            await self.network_connection.write(b"APPE %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["150"])
            if data is not None:
                async for data, err in self.__write_data_channel(data):
                    if err is not None:
                        raise err
            else:
                with open(path, "rb") as f:
                    async for data, err in self.__write_data_channel(f):
                        if err is not None:
                            raise err
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["226"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def dele(self, path: str) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Delete a file on the FTP server.
        Returns a tuple of (success, error).
        """
        try:
            await self.network_connection.write(b"DELE %s\r\n" % path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["250"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def rename(self, oldpath: str, newpath: str) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Rename a file on the FTP server from oldpath to newpath.
        Returns a tuple of (success, error).
        """
        try:
            # First specify the old filename
            await self.network_connection.write(b"RNFR %s\r\n" % oldpath.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["350"])
            
            # Then specify the new filename
            await self.network_connection.write(b"RNTO %s\r\n" % newpath.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["250"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def rest_get(self, remote_path: str, local_path: str = None) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Resume a previously interrupted file transfer.
        Checks if file exists locally and on server, compares sizes, and continues download if needed.
        Returns a tuple of (success, error).
        """
        try:
            if local_path is None:
                local_path = str(Path(remote_path).name)

            # Get remote file size
            remote_size, err = await self.__size(remote_path)
            if err is not None:
                raise err

            # Check local file
            local_size = 0
            if Path(local_path).exists():
                local_size = Path(local_path).stat().st_size
                if local_size >= remote_size:
                    return True, None  # File already completely downloaded

            # Set restart point
            await self.network_connection.write(b"REST %d\r\n" % local_size)
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["350"])

            # Start the transfer
            await self.network_connection.write(b"RETR %s\r\n" % remote_path.encode())
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["150"])

            # Open file in append mode
            with open(local_path, "ab") as f:
                async for data, err in self.__read_data_channel():
                    if err is not None:
                        raise err
                    f.write(data)

            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["226"])
            return True, None
        except Exception as e:
            return False, e
    
    async def __quit(self):
        try:
            await self.network_connection.write(b"QUIT\r\n")
            response, err = await self.__read_response()
            if err is not None:
                raise err
            response.expect(["221"])
            return True, None
        except Exception as e:
            return False, e

    @connection_lock
    async def quit(self) -> Coroutine[Any, Any, Tuple[bool, Exception]]:
        """
        Quit the FTP server.
        Returns a tuple of (success, error).
        """
        return await self.__quit()

    async def enum_all(self, path: str = '', depth: int = 3, filter_cb = None) -> AsyncGenerator[Tuple[str, Exception], None]:
        """
        Enumerate all files and directories on the FTP server.
        Returns a generator of (path, error).
        """
        try:
            dirs = [] # must store dirs, because the ftp protocol doesn't support multiple commands in one go
            async for oname, entry, err in self.mlsd(path):
                if err is not None:
                    yield entry, err
                    continue
                
                if filter_cb is not None:
                    res = await filter_cb(entry['type'], entry)
                    if res is False:
                        continue

                yield entry, None

                if entry['type'] == 'dir' and depth > 0:
                    dirs.append(entry['fullpath'])
            
            for path in dirs:
                async for data, err in self.enum_all(path, depth - 1, filter_cb=filter_cb):
                    yield data, None
                    
                    
        except Exception as e:
            yield None, e

async def amain():
    target = FTPTarget("127.0.0.1", 2121)
    #credential = UniCredential(username="anonymous@", stype = asyauthSecret.NONE)
    credential = UniCredential(username="myuser", secret="change_this_password", stype = asyauthSecret.PASSWORD)
    #client = FTPClientConnection(target, credential)
    client = FTPClientConnection(target, credential)
    await client.connect()
    await client.login()
    print('Testing LIST')
    async for data, err in client.list():
        print(data)

    print('Testing MLSD')
    async for fname, entry, err in client.mlsd():
        if err is not None:
            raise err
        print(entry)

    #test the other commands
    print('Testing NOOP')
    _, err = await client.noop()
    if err is not None:
        raise err
    print('Testing ACCT')
    res, err = await client.acct()
    if err is not None:
        # test server doesn't support acct
        pass
    print(res)
    print('Testing SITE HELP')
    res, err = await client.site("HELP")
    if err is not None:
        raise err
    print(res)
    print('Testing RAWCMD HELP')
    res, err = await client.rawcmd("HELP")
    if err is not None:
        raise err
    print(res)
    print('Testing STOR')
    res, err = await client.stor("test.txt", io.BytesIO(b"Hello, world!"))
    if err is not None:
        raise err
    print(res)
    print('Testing REST GET')
    res, err = await client.rest_get("test.txt", "test.txt")
    if err is not None:
        raise err
    print(res)
    print('Testing RENAME')
    res, err = await client.rename("test.txt", "test2.txt")
    if err is not None:
        raise err
    print(res)
    #check if the file was renamed
    res, entry, err = await client.mlst("test2.txt")
    if err is not None:
        raise err
    print(entry)

    #check if the file was deleted
    res, err = await client.dele("test2.txt")
    if err is not None:
        raise err
    print(res)

    res, entry, err = await client.mlst("test2.txt")
    if err is not None:
        print('File not found, as expected')
    else:
        raise Exception("File found, but should have been deleted")
    
    res, err = await client.pwd()
    if err is not None:
        raise err
    print(res)

    #create a directory
    res, err = await client.mkd("testdir")
    if err is not None:
        raise err
    print(res)

    #check if the directory was created
    res, entry, err = await client.mlst("testdir")
    if err is not None:
        raise err
    print(entry)

    #delete the directory
    res, err = await client.rmd("testdir")
    if err is not None:
        raise err
    print(res)

    #check if the directory was deleted
    res, entry, err = await client.mlst("testdir")
    if err is not None:
        print('Directory not found, as expected')
    else:
        raise Exception("Directory found, but should have been deleted")
    
    #create a directory
    res, err = await client.mkd("testdir")
    if err is not None:
        raise err
    print(res)

    #enter the directory
    res, err = await client.cwd("testdir")
    if err is not None:
        raise err
    print(res)

    #create a file in the directory
    res, err = await client.stor("test.txt", io.BytesIO(b"Hello, world!"))
    if err is not None:
        raise err
    print(res)

    #check if the file was created
    res, entry, err = await client.mlst("test.txt")
    if err is not None:
        raise err
    print(entry)
    
    #check if the file contains the correct content after download
    res, err = await client.get("test.txt", "test.txt")
    if err is not None:
        raise err
    print(res)

    with open("test.txt", "rb") as f:
        content = f.read()
    if content != b"Hello, world!":
        raise Exception("File content is incorrect")

    # rename the file
    res, err = await client.rename("test.txt", "test2.txt")
    if err is not None:
        raise err
    print(res)

    # check if the file was renamed
    res, entry, err = await client.mlst("test2.txt")
    if err is not None:
        raise err
    print(entry)

    
    #delete the file
    res, err = await client.dele("test2.txt")
    if err is not None:
        raise err
    print(res)

    # exit the directory
    res, err = await client.cwd("..")
    if err is not None:
        raise err
    print(res)

    # delete the directory
    res, err = await client.rmd("testdir")
    if err is not None:
        raise err
    print(res)

    #check if the directory was deleted
    res, entry, err = await client.mlst("testdir")
    if err is not None:
        print(err)
        print('Directory not found, as expected')
    else:
        raise Exception("Directory found, but should have been deleted")

    
    
    


    await client.disconnect()
if __name__ == "__main__":
    asyncio.run(amain())
