import ipaddress
import socket
import urllib.parse
from urllib.parse import urlparse
import structlog
from scraper.core.exceptions import SSRFBlockedError

logger = structlog.get_logger()

class SSRFGuard:
    """Guards against Server-Side Request Forgery attacks."""

    BLOCKED_CIDRS = [
        ipaddress.ip_network('127.0.0.0/8'),
        ipaddress.ip_network('10.0.0.0/8'),
        ipaddress.ip_network('172.16.0.0/12'),
        ipaddress.ip_network('192.168.0.0/16'),
        ipaddress.ip_network('169.254.0.0/16'),
        ipaddress.ip_network('::1/128'),
        ipaddress.ip_network('fe80::/10'),
        ipaddress.ip_network('fc00::/7'),
    ]

    ALLOWED_PROTOCOLS = {'http', 'https'}

    @staticmethod
    def is_private_ip(ip: str) -> bool:
        """Checks if an IP address is in a blocked private/loopback range."""
        try:
            ip_obj = ipaddress.ip_address(ip)
            if ip_obj.version == 6 and ip_obj.ipv4_mapped:
                ip_obj = ip_obj.ipv4_mapped
                
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast or ip_obj.is_unspecified:
                return True
                
            for cidr in SSRFGuard.BLOCKED_CIDRS:
                if ip_obj in cidr:
                    return True
            return False
        except ValueError:
            return False

    def validate_url(self, url: str) -> str:
        """
        Validates and returns sanitized URL, raises SSRFBlockedError if blocked.
        """
        try:
            parsed = urlparse(url)
        except Exception as e:
            raise SSRFBlockedError(f"Invalid URL format: {e}")

        if parsed.scheme not in self.ALLOWED_PROTOCOLS:
            raise SSRFBlockedError(f"Protocol '{parsed.scheme}' not allowed")

        hostname = parsed.hostname
        if not hostname:
            raise SSRFBlockedError("No hostname provided")

        try:
            addr_info = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in addr_info:
                ip = sockaddr[0]
                if self.is_private_ip(ip):
                    raise SSRFBlockedError(f"Resolved to blocked IP: {ip}")
        except socket.gaierror:
            # Fail closed to prevent DNS rebinding or resolving internal hostnames
            raise SSRFBlockedError(f"Could not resolve hostname: {hostname}")
            
        return url

    def validate_redirect(self, original_url: str, redirect_url: str, hop_count: int, max_hops: int = 5) -> str:
        """Re-validates redirect target."""
        if hop_count > max_hops:
            raise SSRFBlockedError(f"Max redirect hops ({max_hops}) exceeded")
            
        validated_url = self.validate_url(redirect_url)
        
        orig_parsed = urlparse(original_url)
        new_parsed = urlparse(validated_url)
        
        if orig_parsed.netloc != new_parsed.netloc:
            safe_orig = original_url.replace(orig_parsed.netloc, orig_parsed.netloc.split('@')[-1])
            safe_new = redirect_url.replace(new_parsed.netloc, new_parsed.netloc.split('@')[-1])
            logger.warning("cross_origin_redirect", original=safe_orig, redirect=safe_new)
            
        return validated_url
