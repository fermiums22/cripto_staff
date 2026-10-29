# Home server access

Verified 2026-10-29. Local repository: `D:\w_spase\cripto_staff`.
Remote repository: `https://github.com/fermiums22/cripto_staff.git`.

## Network

Windows WireGuard profile `codex-home` starts automatically. It routes only
`192.168.0.2/32` and `192.168.0.8/32` through the home VPN. Normal internet and
DNS use the office network. Profile files are outside Git in
`C:\Users\v.taranov\.ssh\codex-network`.

The old full-tunnel profile `fermiums` is stopped and its service startup is
Manual. **Do not activate both profiles together:** they reuse one VPN identity.
This is a separate routing profile, not a separate VPN peer or independent relay.

## Verified SSH path

Run in the repository root from PowerShell:

```powershell
ssh -T -i .\work-pc-to-codex-home_ed25519.txt -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=5 root@192.168.0.2 'hostname; pct list'
```

The real private key filename ends in `.txt`. It is intentionally ignored by
Git, as are its extensionless and public-key variants. Do not print its contents.
The key needs Windows ACL permissions restricted to its owner.

Proxmox host: `pve`, `root@192.168.0.2`. Observed ED25519 host-key fingerprint:
`SHA256:c2X6nG9ksMO7wqAjrAOJ0ebsr6hZRYzFblnmnd7elBM`.
The fingerprint was accepted on first connection, not independently authenticated.

Development container: CT **103**, name `codex-home`, IP `192.168.0.8`.
Workspace: `/home/codex/workspace`; regular user: `codex`.
Direct SSH authentication to `codex@192.168.0.8` has not been configured.
Use the verified Proxmox path:

```powershell
ssh -T -i .\work-pc-to-codex-home_ed25519.txt -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.0.2 'pct exec 103 -- runuser -u codex -- id'
```

For multiline commands, avoid nested Windows/Linux shell quoting. Pipe a literal
PowerShell here-string containing Python into
`ssh ... root@192.168.0.2 'pct exec 103 -- python3 -'`.
Use `subprocess.run([...], check=True)` inside Python. Run application code as
`codex`; use container root only for installation/service administration.

Read `/home/codex/workspace/AGENTS.md` and relevant sections of
`/home/codex/workspace/CHATGPT-SERVER-CONTEXT.md` before server changes.
Those files may reference credentials: do not copy secrets into this repository.

## Nika pause and recovery

Nika was paused on 2026-10-29. Nika/Qwen services, their timers,
`ha-agent-bridge` and `sokol-learning-consolidator` were stopped; previously
enabled units were disabled. Models remain in place. The service named
`qwen-chat` was actually running a Ministral model at the time of inspection.

CT 103 backup directory:
`/root/config-backups/nika-pause-20261029T070626Z`.

It contains a private configuration/source/memory archive, original unit states,
model path/size inventory, SHA256 checksum, verification record, and `resume.py`.
Gzip CRC and both archived SQLite databases passed verification. Large model
files and virtual environments were not duplicated. The backup is on the same
server, not an off-server disaster recovery copy.

Restore previously enabled/running services from Proxmox:

```bash
pct exec 103 -- python3 /root/config-backups/nika-pause-20261029T070626Z/resume.py
```

This restores service state without replacing current memory with old data.
Restore script syntax was checked; a full restart was intentionally not performed.

GPU: RTX 5070, 12227 MiB VRAM; usage dropped from 9779 MiB to 0 MiB after pause.
Check on Proxmox with `nvidia-smi`. The container has GPU devices, but no
`nvidia-smi` command on its default PATH.

## Services to preserve

- VM 100: Home Assistant.
- VM 101: TrueNAS.
- CT 102: VPN gateway.
- CT 105: home-edge.
- CT 103: browser workspace and shared Codex services.

Do not stop the entire development container to stop a single application.

## Trading project

Source: `/home/codex/workspace/cripto_staff`, owned by `codex`.
Service: `cripto-paper.service` (experimental spot simulation, no real orders).
Windows status: `powershell -ExecutionPolicy Bypass -File .\status.ps1` from the repository root.
GPU training requires `LD_LIBRARY_PATH=/opt/nvidia-driver`; the main paper
service performs CPU inference. Nika remains paused.

Downloads must use direct home internet, not VPN. The verified CT 103 default
route is `192.168.0.1` on `eth0`; remove proxy environment variables for download
processes. Do not change the remote-access tunnel to accelerate downloads.

Bybit credentials: `secrets/bybit.key` in the project directory, mode 0600,
parent directory 0700. Local source `crypto_cey` is ignored by Git. First line is
the label, then API key and secret. Never print the file or raw authenticated API
responses. The owner explicitly chose Read-Write permissions; real trading is
still prohibited until separately authorized. `check_api.py` checks authentication
using only GET `/v5/user/query-api` and prints no credential values.
