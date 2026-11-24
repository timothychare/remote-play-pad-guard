"""Simulated tests for remote-play-pad-guard. Uses fake files; touches no real hardware."""
import grp, os, signal, subprocess, sys, tempfile, time
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "remote-play-pad-guard"

tmp = tempfile.TemporaryDirectory()
root = Path(tmp.name)
logs = root / "steam/logs"; logs.mkdir(parents=True)
usb = root / "usb"
PADS, OTHER = ("1-1", "1-2"), "1-3"
for name, v, p in (("1-1", "1234", "abcd"), ("1-2", "1234", "ef01"), (OTHER, "5678", "abcd")):
    d = usb / name; d.mkdir(parents=True)
    (d / "idVendor").write_text(v + "\n"); (d / "idProduct").write_text(p + "\n")
    (d / "authorized").write_text("1")
(usb / "1-1:1.0").mkdir()
config = root / "devices"
config.write_text("# comment\n\n1234:ABCD  # upper case is fine\n1234:ef01\n")
S, R = logs / "streaming_log.txt", logs / "remote_connections.txt"
# history containing a start and no end: must be ignored at startup
S.write_text("[x][1.0] Streaming started to old client\n"); R.write_text("")
pid = root / "steam.pid"
def start_fake():
    f = subprocess.Popen(["bash", "-c", "printf steam > /proc/$$/comm; while :; do read -t 1 < /dev/zero -N 0; sleep 0.2; done"])
    pid.write_text(str(f.pid)); return f

# Lines in the format Steam logged in November 2026 (times and ids are made up)
ACC = "[2026-01-01 00:00:00] Responding to streaming request 1 from 2 with k_ERemoteDeviceStreamingSuccess"
CAN = "[2026-01-01 00:00:00] Received streaming cancel request 1 with device ID 3 from 2"
STA = "[2026-01-01 00:00:00][1.000000] Streaming started to Client at 0.0.0.0:0, audio channels = 2, MTU = 1200"
STOPDESK = "[2026-01-01 00:00:00][2.000000] >>> Stopped desktop stream"
END = "[2026-01-01 00:00:00][3.000000] Encoding complete"

fails = 0
def report(name, ok, detail=""):
    global fails
    fails += not ok
    print("PASS" if ok else "FAIL", name, detail)
def add(f, line):
    with open(f, "a") as h: h.write(line + "\n")
def state(name):
    return (usb / name / "authorized").read_text().strip()
def check(name, want, wait=0.7):
    time.sleep(wait)
    pads, other = [state(p) for p in PADS], state(OTHER)
    report(name, pads == [want] * len(PADS) and other == "1", f"(pads={pads}, other={other})")
def run(*args):
    return subprocess.run([GUARD, *args], capture_output=True, text=True, timeout=10)

rule = run("--config", config, "--print-udev-rule")
group = grp.getgrgid(os.getgid()).gr_name
rules = [l for l in rule.stdout.splitlines() if not l.startswith("#")]
report("udev rule covers each listed device", rule.returncode == 0 and len(rules) == 2
       and 'ATTR{idVendor}=="1234", ATTR{idProduct}=="abcd"' in rules[0]
       and 'ATTR{idProduct}=="ef01"' in rules[1]
       and all(f"chgrp {group} /sys%p/authorized" in l for l in rules))
bad = root / "bad"
report("missing device list -> exit 2", run("--config", bad).returncode == 2)
bad.write_text("# nothing\n"); report("empty device list -> exit 2", run("--config", bad).returncode == 2)
bad.write_text("not-an-id\n"); report("invalid ID -> exit 2", run("--config", bad).returncode == 2)

fake = start_fake()
for p in PADS: (usb / p / "authorized").write_text("0")  # leftover from an unclean exit
out = open(root / "out", "w")
g = subprocess.Popen([GUARD, "--config", config, "--steam-dir", root / "steam", "--usb-dir", usb,
                      "--pid-file", pid, "--pending-timeout", "8"], stdout=out, stderr=out)
check("startup restores leftover off; old history ignored", "1")
add(R, ACC); check("request accepted -> off", "0")
add(S, STA); check("stream started -> off", "0")
add(S, STOPDESK); check("desktop->game switch stays off", "0")
check("stays off past pending timeout while streaming", "0", 8.5)
add(S, END); check("stream ended -> on", "1")
add(R, ACC); check("second request -> off", "0")
add(R, CAN); check("cancelled -> on", "1")
add(R, ACC); check("third request -> off", "0")
check("never starts -> on after timeout", "1", 8.5)
add(R, ACC); time.sleep(.6); add(S, STA); check("streaming", "0")
add(R, ACC); time.sleep(.6); add(S, END); check("reconnect: old end ignored", "0")
add(S, STA); check("reconnected", "0")
add(S, "x" * 100); S.rename(logs / "streaming_log.previous.txt"); S.write_text("new\n")
check("log rotation stays off", "0")
add(S, END); check("end seen after rotation -> on", "1")
add(R, ACC); time.sleep(.6); add(S, STA); check("streaming again", "0")
fake.kill(); fake.wait(); check("Steam dies -> on", "1", 6)
fake = start_fake(); time.sleep(.3)
add(R, ACC); check("off before service stop", "0", 0.7)
g.send_signal(signal.SIGTERM); g.wait(5); check("service stopped -> on", "1", 0.1)
fake.kill(); fake.wait()
print((root / "out").read_text()); print("FAILURES:", fails)
sys.exit(bool(fails))
