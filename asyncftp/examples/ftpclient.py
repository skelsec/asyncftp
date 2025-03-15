import sys
import os
import asyncio
import traceback
import ntpath
import fnmatch
import datetime
import time
import shlex
import tqdm
import inspect
import typing
from typing import List, Dict

from asyncftp.external.aiocmd.aiocmd import aiocmd


from asyncftp.common.factory import FTPConnectionFactory
from asyncftp.connection import FTPClientConnection
from asyncftp.common.target import FTPTarget
from asyncftp._version import __banner__

# python3.11 -m asyncftp.examples.ftpclient 'ftp+plain-password://myuser:change_this_password@127.0.0.1:2121' login list help feat stat "cwd ../" cdup "pwd" "size file.txt" "get file.txt" "put test.txt"


class FTPClient(aiocmd.PromptToolkitCmd):
    def __init__(self, url = None, silent = False):
        aiocmd.PromptToolkitCmd.__init__(self, ignore_sigint=False) #Setting this to false, since True doesnt work on windows...
        self.conn_url:str = None
        if url is not None:
            self.conn_url = FTPConnectionFactory.from_url(url)
        self.connection:FTPClientConnection = None
        self.is_anon:bool = False
        self.silent:bool = silent
        self.aliases:Dict[str, str] = {
            '?': 'help',
            'ls': 'list',
            'exit': 'quit',
            'rm': 'delete',
            'cd': 'cwd',
        }
        self.__current_path = '/'


    async def refresh_prompt(self):
        try:
            path, err = await self.connection.pwd()
            if err is not None:
                raise err
            self.__current_path = path
            prompt = '%s' % self.connection.target.get_hostname_or_ip()
            if self.connection.credential.username is not None:
                prompt = '%s@%s' % (self.connection.credential.username, prompt)
            else:
                prompt = 'anonymous@%s' % prompt
            
            prompt += ':%s$ ' % self.__current_path
            self.prompt = prompt
        except Exception as e:
            return await self.handle_error(e)


    async def handle_error(self, err:Exception):
        print(err)
        return False, err

    async def print(self, *args, **kwargs):
        if self.silent is False:
            print(*args, **kwargs)

    async def do_login(self):
        try:
            # no need to call login, since the connection already does it
            self.connection = self.conn_url.get_connection()
            _, err = await self.connection.connect()
            if err is not None:
                raise err
            await self.print('Connected to FTP server')
            for line in self.connection.banner:
                await self.print(line)
            await self.refresh_prompt()
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_list(self):
        try:
            async for line, err in self.connection.list():
                if err is not None:
                    raise err
                await self.print(line)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_logout(self):
        try:
            await self.connection.quit()
        except Exception as e:
            return await self.handle_error(e)

    async def do_rhelp(self, command:str = ''):
        try:
            async for line, err in self.connection.help(command):
                if err is not None:
                    raise err
                await self.print(line)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_feat(self):
        try:
            async for line, err in self.connection.feat():
                if err is not None:
                    raise err
                await self.print(line)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_syst(self):
        try:
            async for line, err in self.connection.syst():
                if err is not None:
                    raise err
                await self.print(line)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_stat(self):
        try:
            async for line, err in self.connection.stat():
                if err is not None:
                    raise err
                await self.print(line)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_cwd(self, path:str):
        try:
            _, err = await self.connection.cwd(path)
            if err is not None:
                raise err
            await self.print('Changed working directory to %s' % path)
            await self.refresh_prompt()
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_cdup(self):
        try:
            _, err = await self.connection.cdup()
            if err is not None:
                raise err
            await self.print('Changed working directory to parent')
            await self.refresh_prompt()
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_pwd(self):
        try:
            path, err = await self.connection.pwd()
            if err is not None:
                raise err
            await self.print('Current working directory: %s' % path)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_size(self, path:str):
        try:
            size, err = await self.connection.size(path)
            if err is not None:
                raise err
            await self.print('Size of %s: %s' % (path, size))
            return True, None
        except Exception as e:
            return await self.handle_error(e)
    
    # no need to implement these, since the connection already does it
    #async def do_type(self, type:str):
    #    try:
    #        _, err = await self.connection.type(type)
    #        if err is not None:
    #            raise err
    #        await self.print('Type set to %s' % type)
    #        return True, None
    #    except Exception as e:
    #        return await self.handle_error(e)
    #
    #async def do_pasv(self):
    #    try:
    #        target, err = await self.connection.pasv()
    #        if err is not None:
    #            raise err
    #        await self.print('Passive mode set to %s' % target)
    #        return True, None
    #    except Exception as e:
    #        return await self.handle_error(e)   

    async def do_get(self, path:str):
        try:
            fsize, err = await self.connection.size(path)
            if err is not None:
                raise err
            await self.print('Downloading %s (%s bytes)' % (path, fsize))
            pbar = tqdm.tqdm(total=fsize, unit='B', unit_scale=True)
            with open(path, 'wb') as f:
                async for data, err in self.connection.get_file(path):
                    if err is not None:
                        raise err
                    f.write(data)
                    pbar.update(len(data))
            pbar.close()
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_put(self, path:str):
        try:
            fsize = os.path.getsize(path)
            await self.print('Uploading %s (%s bytes)' % (path, fsize))
            pbar = tqdm.tqdm(total=fsize, unit='B', unit_scale=True)
            with open(path, 'rb') as f:
                while True:
                    data = f.read(65536)
                    if len(data) == 0:
                        break
                    _, err = await self.connection.appe(path, data)
                    if err is not None:
                        raise err
                    pbar.update(len(data))
            pbar.close()
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_rename(self, oldpath:str, newpath:str):
        try:
            _, err = await self.connection.rename(oldpath, newpath)
            if err is not None:
                raise err
            await self.print('Renamed %s to %s' % (oldpath, newpath))
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_delete(self, path:str):
        try:
            _, err = await self.connection.dele(path)
            if err is not None:
                raise err
            await self.print('Deleted %s' % path)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_mkdir(self, path:str):
        try:
            _, err = await self.connection.mkd(path)
            if err is not None:
                raise err
            await self.print('Created directory %s' % path)
            return True, None
        except Exception as e:
            return await self.handle_error(e)

    async def do_rmdir(self, path:str):
        try:
            _, err = await self.connection.rmd(path)
            if err is not None:
                raise err
            await self.print('Removed directory %s' % path)
            return True, None
        except Exception as e:
            return await self.handle_error(e)


async def amain(url:str, silent:bool=False, commands:List[str]=None, no_interactive:bool=False, continue_on_error:bool=False):
    client = FTPClient(url, silent)
    if len(commands) == 0:
        if no_interactive is True:
            print('Not starting interactive!')
            sys.exit(1)
        _, err = await client._run_single_command('login', [])
        if err is not None:
            sys.exit(1)
        await client.run()
    else:
        try:
            for command in commands:
                if command == 'i':
                    await client.run()
                    sys.exit(0)
                
                cmd = shlex.split(command)
                if cmd[0] == 'login':
                    _, err = await client.do_login()
                    if err is not None:
                        sys.exit(1)
                    continue
                
                print('>>> %s' % command)
                _, err = await client._run_single_command(cmd[0], cmd[1:])
                if err is not None and continue_on_error is False:
                    print('Batch execution stopped early, because a command failed!')
                    sys.exit(1)
            sys.exit(0)
        finally:
            await client.do_logout()

def main():
    import argparse
    import platform
    import logging
    from asysocks import logger as asylogger
    from asyauth import logger as asyauthlogger
    
    parser = argparse.ArgumentParser(description='Interactive SMB client')
    parser.add_argument('-v', '--verbose', action='count', default=0)
    parser.add_argument('-s', '--silent', action='store_true', help='do not print banner')
    parser.add_argument('-n', '--no-interactive', action='store_true')
    parser.add_argument('-c', '--continue-on-error', action='store_true', help='When in batch execution mode, execute all commands even if one fails')
    parser.add_argument('url', help = 'Connection string that describes the authentication and target. Example: smb+ntlm-password://TEST\\Administrator:password@10.10.10.2')
    parser.add_argument('commands', nargs='*')

    args = parser.parse_args()
    if args.silent is False:
        print(__banner__)

    if args.url is None:
        print("No URL provided")
        return

    asyncio.run(amain(args.url, args.silent, args.commands, args.no_interactive, args.continue_on_error))

if __name__ == '__main__':
    main()