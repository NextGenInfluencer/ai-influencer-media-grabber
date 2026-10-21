"""Isolated yt-dlp worker: only public Internet socket destinations are allowed."""
import ipaddress
import socket


def public_destination(address, family, socktype, proto=0):
    host, port = address[:2]
    addresses = socket.getaddrinfo(host, port, family, socktype, proto)
    if not addresses or any(not ipaddress.ip_address(row[4][0].split('%')[0]).is_global
                            for row in addresses):
        raise OSError('Private or reserved network destinations are not allowed for video downloads.')
    # Connect to the checked numeric address, avoiding a second DNS lookup.
    return addresses[0][4]


def main():
    original_socket = socket.socket

    class PublicSocket(original_socket):
        def connect(self, address):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                address = public_destination(address, self.family, self.type, self.proto)
            return super().connect(address)

        def connect_ex(self, address):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                address = public_destination(address, self.family, self.type, self.proto)
            return super().connect_ex(address)

    socket.socket = PublicSocket
    import yt_dlp
    yt_dlp.main()


if __name__ == '__main__':
    main()
