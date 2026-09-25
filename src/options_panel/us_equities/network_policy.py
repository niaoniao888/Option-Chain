from __future__ import annotations

import argparse
import ipaddress


RFC1918 = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def is_rfc1918(address: ipaddress.IPv4Address) -> bool:
    return any(address in network for network in RFC1918)


def validate_network(host: str, allow_subnet: str) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Network]:
    try:
        address = ipaddress.ip_address(host)
        network = ipaddress.ip_network(allow_subnet, strict=False)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"地址或网段无效：{exc}") from exc
    if not isinstance(address, ipaddress.IPv4Address) or not isinstance(network, ipaddress.IPv4Network):
        raise argparse.ArgumentTypeError("只支持 IPv4")
    if not (address.is_loopback or is_rfc1918(address)):
        raise argparse.ArgumentTypeError("只允许回环或 RFC1918 私网 IPv4，禁止 0.0.0.0 和公网地址")
    subnet_allowed = network.subnet_of(ipaddress.ip_network("127.0.0.0/8")) or any(network.subnet_of(item) for item in RFC1918)
    if not subnet_allowed or address not in network:
        raise argparse.ArgumentTypeError("授权网段必须是包含绑定地址的回环或 RFC1918 私网")
    return address, network


def client_allowed(client_ip: str, network: ipaddress.IPv4Network) -> bool:
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and address in network

