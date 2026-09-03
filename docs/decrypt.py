#!/usr/bin/env python3
"""
Standalone utility to decrypt rclone crypt backup files without rclone.

Prerequisites:
    pip install pynacl

Usage:
    python3 docs/decrypt.py <encrypted_input_file> <decrypted_output_file> <password>
"""

import hashlib
import struct
import sys
from nacl.secret import SecretBox


def decrypt_file(input_path, output_path, password):
    # 1. Derive 32-byte key using rclone's standard scrypt parameters & default salt
    salt = bytes.fromhex("a80df43a8fbd0308a7cab83e581f86b1")
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=16384, r=8, p=1, maxmem=0, dklen=32
    )
    box = SecretBox(key)

    with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
        magic = f_in.read(8)
        assert magic == b"RCLONE\x00\x00", "Error: File is not an rclone crypt file (missing RCLONE magic header)"
        file_nonce = f_in.read(24)
        base_int = struct.unpack("<Q", file_nonce[:8])[0]

        block = 0
        while chunk := f_in.read(65536 + 16):  # 64 KiB plaintext + 16-byte Poly1305 tag
            nonce = struct.pack("<Q", (base_int + block) & 0xFFFFFFFFFFFFFFFF) + file_nonce[8:]
            f_out.write(box.decrypt(chunk, nonce))
            block += 1

    print(f"Decrypted successfully to: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 decrypt.py <encrypted_input_file> <decrypted_output_file>")
        sys.exit(1)

    pw = input("Password: ")
    decrypt_file(sys.argv[1], sys.argv[2], pw)
