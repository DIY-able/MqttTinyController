
# This TOTP for Pico library is written by Edd Mann from UK
# Github: https://github.com/eddmann/pico-2fa-totp

import struct

HASH_CONSTANTS = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]

def left_rotate(n, b):
    return ((n << b) | (n >> (32 - b))) & 0xFFFFFFFF


def expand_chunk(chunk):
    w = list(struct.unpack(">16L", chunk)) + [0] * 64
    for i in range(16, 80):
        w[i] = left_rotate((w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]), 1)
    return w


def sha1(message):
    """
    Secure Hash Algorithm 1 (SHA1) implementation based on https://en.wikipedia.org/wiki/SHA-1#SHA-1_pseudocode

    >>> import binascii
    >>> binascii.hexlify(sha1(b'The quick brown fox jumps over the lazy dog'))
    b'2fd4e1c67a2d28fced849ee1bb76e7391b93eb12'
    >>> binascii.hexlify(sha1(b'The quick brown fox jumps over the lazy cog'))
    b'de9f2c7fd25e1b3afad3e85a0bd17d9b100db4b3'
    >>> binascii.hexlify(sha1(b''))
    b'da39a3ee5e6b4b0d3255bfef95601890afd80709'
    """

    h = HASH_CONSTANTS
    padded_message = message + b"\x80" + \
        (b"\x00" * (63 - (len(message) + 8) % 64)) + \
        struct.pack(">Q", 8 * len(message))
    chunks = [padded_message[i:i+64]
              for i in range(0, len(padded_message), 64)]

    for chunk in chunks:
        expanded_chunk = expand_chunk(chunk)
        a, b, c, d, e = h
        for i in range(0, 80):
            if 0 <= i < 20:
                f = (b & c) | ((~b) & d)
                k = 0x5A827999
            elif 20 <= i < 40:
                f = b ^ c ^ d
                k = 0x6ED9EBA1
            elif 40 <= i < 60:
                f = (b & c) | (b & d) | (c & d)
                k = 0x8F1BBCDC
            elif 60 <= i < 80:
                f = b ^ c ^ d
                k = 0xCA62C1D6
            a, b, c, d, e = (
                left_rotate(a, 5) + f + e + k + expanded_chunk[i] & 0xFFFFFFFF,
                a,
                left_rotate(b, 30),
                c,
                d,
            )
        h = (
            h[0] + a & 0xFFFFFFFF,
            h[1] + b & 0xFFFFFFFF,
            h[2] + c & 0xFFFFFFFF,
            h[3] + d & 0xFFFFFFFF,
            h[4] + e & 0xFFFFFFFF,
        )

    return struct.pack(">5I", *h)


def hmac_sha1(key, message):
    """
    Hash-based Message Authentication Code (HMAC) SHA1 implementation based on https://en.wikipedia.org/wiki/HMAC#Implementation

    >>> import binascii
    >>> binascii.hexlify(hmac_sha1(b'secret', b'message'))
    b'0caf649feee4953d87bf903ac1176c45e028df16'
    >>> binascii.hexlify(hmac_sha1(b'secret', b'another message'))
    b'cb15739d1cc17409a20afab28ba0964ef51fbe3b'
    """

    key_block = key + (b'\0' * (64 - len(key)))
    key_inner = bytes((x ^ 0x36) for x in key_block)
    key_outer = bytes((x ^ 0x5C) for x in key_block)

    inner_message = key_inner + message
    outer_message = key_outer + sha1(inner_message)

    return sha1(outer_message)



def base32_decode(message):
    """
    Decodes the supplied encoded Base32 message into a byte string

    >>> base32_decode('DWRGVKRPQJLNU4GY')
    b'\\x1d\\xa2j\\xaa/\\x82V\\xdap\\xd8'
    >>> base32_decode('JBSWY3DPFQQHO33SNRSA====')
    b'Hello, world'
    """

    padded_message = message + '=' * (8 - len(message) % 8)
    chunks = [padded_message[i:i+8] for i in range(0, len(padded_message), 8)]

    decoded = []

    for chunk in chunks:
        bits = 0
        bitbuff = 0

        for c in chunk:
            if 'A' <= c <= 'Z':
                n = ord(c) - ord('A')
            elif '2' <= c <= '7':
                n = ord(c) - ord('2') + 26
            elif c == '=':
                continue
            else:
                raise ValueError("Not Base32")

            bits += 5
            bitbuff <<= 5
            bitbuff |= n

            if bits >= 8:
                bits -= 8
                byte = bitbuff >> bits
                bitbuff &= ~(0xFF << bits)
                decoded.append(byte)

    return bytes(decoded)



def totp(time, key, step_secs=30, digits=6):
    """
    Time-based One-Time Password (TOTP) implementation based on https://tools.ietf.org/id/draft-mraihi-totp-timebased-06.html

    >>> totp(1602659430, "DWRGVKRPQJLNU4GY", step_secs=30, digits=6)
    ('846307', 30)
    >>> totp(1602659435, "DWRGVKRPQJLNU4GY", step_secs=30, digits=6)
    ('846307', 25)
    >>> totp(1602659430, "DWRGVKRPQJLNU4GY", step_secs=30, digits=4)
    ('6307', 30)
    >>> totp(1602659430, "DWRGVKRPQJLNU4GY", step_secs=15, digits=6)
    ('524508', 15)
    """

    hmac = hmac_sha1(base32_decode(key), struct.pack(">Q", time // step_secs))
    offset = hmac[-1] & 0xF
    code = ((hmac[offset] & 0x7F) << 24 |
            (hmac[offset + 1] & 0xFF) << 16 |
            (hmac[offset + 2] & 0xFF) << 8 |
            (hmac[offset + 3] & 0xFF))
    code = str(code % 10 ** digits)
    return (
        "0" * (digits - len(code)) + code,
        step_secs - time % step_secs
    )

# -----------------------------------------------------------------------