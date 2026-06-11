# Firecracker microVM sandboxes (`SANDBOX_ENGINE=firecracker`)

This mode runs **Linux KVM microVMs** via the [Firecracker](https://firecracker-microvm.github.io/) `firecracker` binary instead of Docker containers. **Warm pool**, **templates metadata**, and **REST routes** are unchanged; only the **execution plane** swaps.

## Requirements (all on the **Linux** machine that runs the API)

| Requirement | Notes |
|-------------|--------|
| **Linux + `/dev/kvm`** | Firecracker is not supported on macOS directly. Run the API **inside Colima** (`colima ssh`), a Linux VM, or bare metal. |
| **`firecracker` binary** | e.g. `/usr/local/bin/firecracker` from [releases](https://github.com/firecracker-microvm/firecracker/releases). |
| **Uncompressed `vmlinux`** | Guest kernel image path (`FIRECRACKER_KERNEL`). |
| **ext4 rootfs** with **sshd** | Path (`FIRECRACKER_ROOTFS`). Your SSH **private** key on the API host must match **`authorized_keys`** baked into the image for `FIRECRACKER_SSH_USER` (usually `root`). |
| **TAP devices** | One tap per concurrent VM slot, e.g. `tapfc0` … `tapfc7` on a bridge with routing/NAT to the guest subnet. See scripts below. |
| **`ssh` and `scp` on PATH** | Used for commands and file writes. |

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `SANDBOX_ENGINE` | `docker` | Set to `firecracker` (aliases: `fc`, `microvm`). |
| `FIRECRACKER_BINARY` | `/usr/local/bin/firecracker` | Firecracker executable. |
| `FIRECRACKER_KERNEL` | *(required)* | Host path to guest `vmlinux`. |
| `FIRECRACKER_ROOTFS` | *(required)* | Host path to golden **ext4** rootfs (copied per VM). |
| `FIRECRACKER_GATEWAY` | `172.16.0.1` | Guest default gateway (host bridge side). |
| `FIRECRACKER_SUBNET_PREFIX` | `172.16.0` | First three octets; last octet = `FIRECRACKER_GUEST_OCTET_BASE + slot`. |
| `FIRECRACKER_GUEST_OCTET_BASE` | `10` | Starting last octet for slot `0`. |
| `FIRECRACKER_TAP_PATTERN` | `tapfc{slot}` | Tap interface name; `{slot}` = `0 … FIRECRACKER_TAP_SLOTS-1`. |
| `FIRECRACKER_TAP_SLOTS` | `8` | Rotate slots for new VMs; **each tap must exist**. |
| `FIRECRACKER_SSH_USER` | `root` | SSH user in the guest. |
| `FIRECRACKER_SSH_KEY` | *(required)* | Path to **private** SSH key for the guest. |
| `FIRECRACKER_SSH_KNOWN_HOSTS` | `/dev/null` | Passed to `ssh`/`scp` (dev default). |
| `FIRECRACKER_ENABLE_PCI` | `false` | Set `true` only if you pass `--enable-pci` to Firecracker. |

`SANDBOX_ISOLATION` / gVisor apply **only** to `SANDBOX_ENGINE=docker`.

## Warm pool

`MultiWarmSandboxPool` is unchanged. Each warm sandbox is still a normal `POST /sandboxes` provisioning path via `_create_sandbox_fresh`.

**Docker template warm snapshots** (`docker commit` images) are **not** used under Firecracker. Registered templates get a sentinel warm marker so the pool still keys on `(template_id, cpu, mem, timeout)`; guests boot from **`FIRECRACKER_ROOTFS`** (or a per-request `.ext4` path when `from_snapshot_image` points to a host file).

Keep **`SANDBOX_WARM_POOL_SIZE ≤ FIRECRACKER_TAP_SLOTS`** (and ≤ number of real taps) so each idle sandbox has its own tap/IP.

Example tap + bridge script (run with **sudo** on the Linux host): `scripts/firecracker/colima-taps.example.sh`.

## Networking sketch (inside Colima / Linux)

1. Create a bridge (once), e.g. `br-fc` with `172.16.0.1/24`.
2. For each slot `n` in `0..N-1`:

   ```bash
   sudo ip tuntap add dev tapfc$n mode tap
   sudo ip link set tapfc$n master br-fc
   sudo ip link set tapfc$n up
   ```

3. Enable IPv4 forwarding + NAT from `br-fc` to your uplink (same steps as any Linux router).

4. Guest kernel boot uses `ip=<guest>::<gw>:255.255.255.0::eth0:off` (see `firecracker_plane.py`).

Adjust addresses if you use a different subnet.

## Colima workflow (summary)

1. `colima ssh` into the Linux VM.  
2. Install Firecracker + assets; create taps + bridge as above.  
3. Build or copy an ext4 rootfs with `sshd` and your public key in `/root/.ssh/authorized_keys`.  
4. Export env vars and run the API **in that same VM** (or ensure the process can reach the same paths and `/dev/kvm`).

You can still use **`DOCKER_HOST`** on your Mac for **Docker-backed** dev; Firecracker mode is typically enabled only on the Linux host where KVM is available.

## Limitations

- **Filesystem snapshots** (`POST /sandboxes/{id}/snapshot` / `docker commit`) are unavailable (no Docker).  
- **Template build** that relies on Docker images is skipped; use a prebuilt rootfs.  
- Pause/resume uses Firecracker `PATCH /vm` (`Paused` / `Resumed`).

## See also

- `docs/SANDBOX_BACKENDS_FUTURE.md` — comparison with Docker + gVisor.  
- `docs/REMOTE_SANDBOX_VM.md` — running Docker (and this API) on a Linux VM from macOS.
