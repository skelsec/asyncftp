
from typing import List
class FTPException(Exception):
    pass

class FTPResponseException(FTPException):
    def __init__(self, code: str, messages: List[str]):
        self.code = code
        self.messages = messages
    
    def __str__(self):
        return f"FTPResponseException: {self.code} {','.join(self.messages)}"

class FTPResponseExpectationException(FTPResponseException):
    def __init__(self, code: str, messages: List[str], expected: List[str]):
        super().__init__(code, messages)
        self.expected = expected

    def __str__(self):
        messages = ','.join(self.messages)
        expected = ','.join(self.expected)
        return f"FTPResponseExpectationException: {self.code} {messages} expected {expected}"

class FTPCommandException(FTPResponseException):
    def __init__(self, command: str, code: str, messages: List[str]):
        super().__init__(code, messages)
        self.command = command

    def __str__(self):
        messages = ','.join(self.messages)
        return f"FTPCommandException: {self.command} {self.code} {messages}"

class FTPAuthenticationException(FTPException):
    def __init__(self, code: str, messages: List[str]):
        super().__init__(code, messages)