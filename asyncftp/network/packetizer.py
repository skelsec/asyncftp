from asysocks.unicomm.common.packetizers import Packetizer

class FTPPacketizer(Packetizer):
    def __init__(self, max_read_size: int = 65535):
        super().__init__(max_read_size)
        self.in_buffer = b''

    def process_buffer(self):
        # ftp is line based protocol
        # so we need to split the buffer by \r\n
        # and yield the lines
        while len(self.in_buffer) > 0:
            pos = self.in_buffer.find(b'\n')
            if pos == -1:
                break
            temp = self.in_buffer[:pos]
            self.in_buffer = self.in_buffer[pos + 1:]
            yield temp.decode()
           

    async def data_out(self, data:bytes):
        yield data

    async def data_in(self, data):
        if data is None:
            for packet in self.process_buffer():
                yield packet
        else:
            self.in_buffer += data
            for packet in self.process_buffer():
                yield packet
