#!/usr/bin/env python3
"""Run a command under a pseudo-terminal (like an operator's SSH session) and write every output
line to LOG prefixed with elapsed seconds since start. Exit code = command exit code."""
import fcntl, os, pty, struct, sys, termios, time

def main():
    log_path = sys.argv[1]
    cmd = sys.argv[sys.argv.index("--") + 1:]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.setdefault("TERM", "xterm")
        os.execvp(cmd[0], cmd)
    # janela de 120x40, como uma sessão SSH (sem isso o terminal informa largura 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    buf = b""
    with open(log_path, "w", buffering=1) as log:
        log.write(f"[0.000] START {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {' '.join(cmd)}\n")
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                data = b""
            if not data:
                break
            buf += data
            # answer interactive prompts the way the operator would (isolated test only)
            if b"BECOME password:" in buf or b"[sudo] password for" in buf:
                os.write(fd, (os.environ.get("SIM_BECOME_PW", "") + "\n").encode())
                buf = buf.replace(b"BECOME password:", b"BECOME password: <answered>\n").replace(b"[sudo] password for", b"[sudo] answered for")
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                log.write(f"[{time.time()-t0:.3f}] {ln.decode(errors='replace').rstrip(chr(13))}\n")
        if buf:
            log.write(f"[{time.time()-t0:.3f}] {buf.decode(errors='replace')}\n")
        _, status = os.waitpid(pid, 0)
        rc = os.waitstatus_to_exitcode(status)
        log.write(f"[{time.time()-t0:.3f}] END rc={rc}\n")
    sys.exit(rc)

if __name__ == "__main__":
    main()
