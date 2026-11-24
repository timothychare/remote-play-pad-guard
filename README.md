# remote-play-pad-guard

Turns off controllers plugged into your Linux PC while Steam Remote Play is streaming, so the
controller on your phone, tablet or other client can become player 1. Turns them back on when the
stream ends.

It is a single Python script with no dependencies, run as a systemd user service.

This is an unofficial project, not affiliated with or endorsed by Valve.

## Is this your problem?

While streaming a game from your PC, the controller connected to your phone or other client works in
Steam's menus but not in the game. If you unplug the controller from the PC and reconnect, it works.

Steam numbers controllers in connection order. One already plugged into the PC takes XInput slot 0
(player 1), so the streaming client's controller gets a later slot. Steam's menus accept any
controller, but some games only listen to player 1.

To check, look at Steam's log after streaming with the PC's controller plugged in:

```
grep -E 'Local Device Found|Remote Device Found|Product:|XInput slot' ~/.local/share/Steam/logs/controller.txt | tail -12
```

If the `Local Device` has slot 0 and the streaming client's controller (`Remote Device`) has slot 1
or higher, this script is meant for you. If the client's controller already has slot 0, the cause is
something else.

## Requirements

- Linux with systemd and udev
- Python 3.7 or newer
- Steam installed as a normal package. The Flatpak and Snap versions are untested. Flatpak is unlikely
  to work without changes, because its process ID may not match the one the host sees.
- A controller connected by USB, including USB wireless dongles. Controllers paired directly over
  Bluetooth aren't handled.
- `sudo` access for installing one udev rule
- `lsusb` (package `usbutils`) for finding your controller's ID

## Install

Download or clone this repository and open a terminal in its folder.

### 1. Find your controller's USB ID

Run this with the controller plugged in:

```
lsusb
```

Each line contains an ID such as `1234:abcd`. If you can't tell which line is your controller, unplug
it, run `lsusb` again, and see which line disappears.

Pick only the controller. Any device you list is cut off during streams, so don't list a keyboard,
mouse or USB hub. A dongle that serves several devices turns all of them off.

### 2. Install the script and service

```
install -D -m 755 remote-play-pad-guard ~/.local/bin/remote-play-pad-guard
install -D -m 644 remote-play-pad-guard.service ~/.config/systemd/user/remote-play-pad-guard.service
install -D -m 644 devices.example ~/.config/remote-play-pad-guard/devices
```

### 3. List your controller

Open `~/.config/remote-play-pad-guard/devices` in a text editor and replace `1234:abcd` with your ID.
To handle several controllers, put one ID on each line.

### 4. Install the udev rule

The rule lets the script turn the listed devices off and on without running as root. Look at it first:

```
~/.local/bin/remote-play-pad-guard --print-udev-rule
```

It should contain your ID and your own group. Then install it:

```
~/.local/bin/remote-play-pad-guard --print-udev-rule | sudo tee /etc/udev/rules.d/70-remote-play-pad-guard.rules
sudo udevadm control --reload
```

**Unplug the controller's USB cable or dongle from the PC, wait a few seconds, and plug it back in.**
The rule only applies when the device is added.

### 5. Check the permission

Replace `abcd` with the second half of your ID:

```
grep -l abcd /sys/bus/usb/devices/*/idProduct
```

This prints a path such as `/sys/bus/usb/devices/1-2/idProduct`. Here `1-2` is the USB port; use
yours in the next command:

```
ls -l /sys/bus/usb/devices/1-2/authorized
```

It should show `-rw-rw-r--`, then `root` and your group.

### 6. Start the service

```
systemctl --user daemon-reload
systemctl --user enable --now remote-play-pad-guard
systemctl --user status remote-play-pad-guard
```

The status should say `active (running)`. The service also starts at each login.

### 7. Try a stream

1. Leave the controller plugged into the PC, and close any stream that is already open. The script
   only reacts to new stream requests.
2. Connect from your phone or other client and start a game. The PC's controller should disconnect.
3. Check that the client's controller works in the game.
4. End the stream and check that the PC's controller works again.

If it doesn't work, see [Troubleshooting](#troubleshooting).

## Configuration

After changing the device list, repeat steps 4 and 5, then restart the service:

```
systemctl --user restart remote-play-pad-guard
```

Options can be added to the `ExecStart` line of the service file. Run
`systemctl --user daemon-reload` and restart the service afterwards.

| Option | Default | Use it when |
|---|---|---|
| `--config` | `~/.config/remote-play-pad-guard/devices` | You keep the device list elsewhere |
| `--steam-dir` | `~/.local/share/Steam` | Steam's `logs` folder is somewhere else, for example under `~/.steam/steam` |
| `--pid-file` | `~/.steam/steam.pid` | Steam's PID file is somewhere else |
| `--pending-timeout` | 60 | Your client takes longer than a minute to connect |

In the service file, write `%h` for your home folder instead of `~`.

## How it works

### Turning controllers off and on

Each USB device has an `authorized` file under `/sys/bus/usb/devices/`. Writing `0` makes the kernel
stop using the device; writing `1` brings it back. The controller stays plugged in, but programs,
including Steam, see it disconnect.

Only root can normally write that file. The udev rule gives your primary group write access for the
listed USB IDs only. Any program running with that group can also toggle those devices. On systems
where all users share one primary group, such as `users`, that includes the other users.

The script finds controllers by USB ID, so the port doesn't matter. Two identical controllers are
both turned off.

### Detecting a stream

The script checks two files in Steam's `logs` folder five times a second. It reads only new lines, and
handles Steam rotating the logs.

| Log line | File | Meaning |
|---|---|---|
| `Responding to streaming request ... StreamingSuccess` | `remote_connections.txt` | Request accepted |
| `Received streaming cancel request` | `remote_connections.txt` | Request cancelled |
| `Streaming started to ...` | `streaming_log.txt` | Stream running |
| `Encoding complete` or `PipeWire: Deinitializing streaming` | `streaming_log.txt` | Stream ended |

Don't use `>>> Stopped desktop stream` as the end marker. Steam also logs it when the stream switches
from the desktop to the game, so the controller would come back on mid-game.

### States

| State | Controllers | Leaves this state when |
|---|---|---|
| idle | On | A request is accepted (to pending) |
| pending | Off | The stream starts (to streaming); the request is cancelled, or the timeout passes (to idle) |
| streaming | Off | The stream ends (to idle); a new request is accepted (to pending) |

Other behaviour:

- **Steam closes or crashes:** checked every 5 seconds while controllers are off; goes to idle.
- **Reconnecting mid-stream:** an end line from the old stream is ignored while a new request is pending.
- **Service starts or stops:** the controllers are turned on. If the service restarts mid-stream, they
  stay on until the next request.
- **Replug or reboot:** the kernel turns the controller back on. If it is plugged in mid-stream, the
  script leaves it on until the next request.

### Timing

The PC's controller has to be gone before the client's controller arrives. In six measured streams,
the client's controller arrived about 3 to 7 seconds after the request was accepted. In both real
stream tests with the controller turned off this way, Steam closed it about a second or less after
accepting the request.

## Troubleshooting

### A controller is stuck off

Try these in order:

1. Restart the service, which turns the listed controllers on:

   ```
   systemctl --user restart remote-play-pad-guard
   ```

2. Unplug it and plug it back in.

3. Find the device that is off, then turn it on by hand using its port in place of `1-2`:

   ```
   grep -H '^0$' /sys/bus/usb/devices/*/authorized
   echo 1 | sudo tee /sys/bus/usb/devices/1-2/authorized
   ```

### Start here for anything else

```
systemctl --user status remote-play-pad-guard
journalctl --user -u remote-play-pad-guard -f
```

Leave the second command running and start a stream. A normal session looks like this:

```
Watching for Steam Remote Play
idle -> pending: stream request accepted
Controller off (1-2)
pending -> streaming: stream started
streaming -> idle: stream ended
Controller on (1-2)
```

| What you see | Likely cause | What to do |
|---|---|---|
| `Could not read the device list`, `lists no devices` or `expected an ID` | The device list is missing, empty or has a typo | Redo Install step 3, then start the service |
| Nothing after `Watching for Steam Remote Play` | Steam's logs are elsewhere or their wording changed | [Check Steam's log lines](#check-steams-log-lines) |
| `Could not turn controller off: ... Permission denied` | udev rule not installed, or controller not replugged since | Redo Install steps 4 and 5 |
| `No listed controller is plugged in` | Controller unplugged, or the ID is wrong | Compare the device list with `lsusb` |
| `pending -> idle: stream never started` while streaming | The start line wasn't recognised, or connecting took over 60 s | Check Steam's log lines, or raise `--pending-timeout` |
| `... -> idle: Steam is not running` while streaming | The PID file is missing or wrong | Compare `cat ~/.steam/steam.pid` with `pgrep -x steam` |
| The controller turns on when the game starts | An end line appeared early | Check Steam's log lines around that time |
| Normal log, but the client's controller still fails in the game | Slot or focus problem | Next two sections |

Some controllers change USB ID when switched to another mode. If `lsusb` shows a different ID, add it
to the device list.

### Check the controller slots

Run the `grep` command from [Is this your problem?](#is-this-your-problem) again. The client's
controller should be followed by `reserving XInput slot 0`.

If the PC's controller still has slot 0 in the same session, it wasn't removed in time. Disconnect,
close the stream, and reconnect. If another controller has slot 0, add its ID to the device list.

### The controller stops working after touching the client's screen

This is a separate problem that the script doesn't fix. It was seen on KDE Plasma, starting when an
input-control prompt opened on the PC. The likely trigger was a touch on the client's screen, which
made Steam try to move the PC's mouse. The game lost focus, and Steam used the controller's desktop
layout until focus came back.

Approve the prompt on the PC. On KDE Plasma you can also change it in System Settings → Application
Permissions → Legacy X11 App Support (wording may vary). Allowing it without asking lets any X11 app
control the mouse and keyboard.

To see focus changes:

```
grep OnFocusWindowChanged ~/.local/share/Steam/logs/controller_ui.txt | tail
```

### Check Steam's log lines

Connect and disconnect once, then run:

```
tail -n 10 ~/.local/share/Steam/logs/remote_connections.txt
grep -E 'Streaming started to|Encoding complete|Deinitializing' ~/.local/share/Steam/logs/streaming_log.txt | tail
```

If the files don't exist, find Steam's `logs` folder and set `--steam-dir`.

Otherwise compare the output with [Detecting a stream](#detecting-a-stream). If the wording changed,
update the patterns (`ACCEPTED`, `CANCELLED`, `STARTED`, `ENDED`) near the top of the script, run the
tests, reinstall the script, and restart the service. The tests use the old wording, so update their
sample lines too.

Steam's logs contain device names, IDs and sometimes addresses. Remove those before posting them in
an issue.

### Run the tests

From the repository folder:

```
python3 test_guard.py
```

This takes about 35 seconds and should end with `FAILURES: 0`. It needs `bash`, uses fake files, and
never touches real devices.

## Pause or remove

Stop it until the next login:

```
systemctl --user stop remote-play-pad-guard
```

Remove it completely:

```
systemctl --user disable --now remote-play-pad-guard
rm ~/.local/bin/remote-play-pad-guard ~/.config/systemd/user/remote-play-pad-guard.service
rm -r ~/.config/remote-play-pad-guard
systemctl --user daemon-reload
sudo rm /etc/udev/rules.d/70-remote-play-pad-guard.rules
sudo udevadm control --reload
```

Then replug the controller to reset its permissions.

## Known limits

- It depends on Steam's log wording, which a Steam update can change. The wording here is from
  November 2026.
- The listed controllers can't be used on the PC during a stream.
- Controllers that aren't listed can still take slot 0.
- If the stream ends without Steam logging it, the controllers stay off until Steam closes, the
  service restarts, or they are replugged.

## What has been tested

This version passed one real stream on one PC, with one wired controller, one client and one game. The
controller was turned off, the client's controller got slot 0 and worked in the game, and the PC's
controller came back afterwards. An earlier version, with the controller's ID written into the script,
also passed one real stream.

Listing several controllers, cancelled requests, reconnecting mid-stream, log rotation and Steam
crashes are covered only by the simulated tests.

## License

[MIT](LICENSE)
