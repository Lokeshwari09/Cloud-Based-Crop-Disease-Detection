# Running in Oracle VirtualBox (private-cloud / IaaS demo)

Idea: the VirtualBox VM plays the role of a cloud server (IaaS). Inside it Docker runs the application containers - the same setup used later on AWS EC2.

> Written from the standard VirtualBox/Ubuntu workflow; not executed while building this project.

## 1. Create the VM
1. Install **Oracle VirtualBox** and download the **Ubuntu Server 22.04/24.04 LTS** ISO.
2. **New** -> name `crop-disease-vm`, type Linux / Ubuntu (64-bit), attach the ISO.
3. Hardware: **2 CPUs, 4096 MB RAM**, **20 GB** disk.
4. **Settings -> Network -> Adapter 1 -> NAT -> Advanced -> Port Forwarding**, add:

| Name | Protocol | Host IP | Host port | Guest port |
|---|---|---|---|---|
| ssh | TCP | 127.0.0.1 | 2222 | 22 |
| web | TCP | 127.0.0.1 | 8080 | 8080 |

5. Start the VM, install Ubuntu, tick **Install OpenSSH server** when asked.

## 2. Install Docker inside the VM
```bash
sudo apt-get update && sudo apt-get install -y unzip
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && exit      # reconnect afterwards
```

## 3. Copy and start the project
From your host machine (PowerShell or terminal):
```bash
scp -P 2222 crop-disease-cloud.zip <vm-user>@127.0.0.1:~
ssh -p 2222 <vm-user>@127.0.0.1
```
Inside the VM:
```bash
unzip crop-disease-cloud.zip && cd crop-disease-cloud
docker compose up --build -d
```

## 4. Use it
Open **http://localhost:8080** in your normal browser (the port-forward sends it into the VM).
Load test from the host: `python scripts/load_test.py --url http://localhost:8080`.

## 5. Ideas for the report
- Take a **snapshot** before/after deployment (VM -> Snapshots) to show rollback.
- **Clone** the VM to create a second server and discuss horizontal scaling.
- Compare: VirtualBox VM (private IaaS) vs AWS EC2 (public IaaS) vs Docker containers (lightweight, shared kernel).

## Troubleshooting
- *VT-x/AMD-V error*: enable virtualization in BIOS/UEFI. On Windows, Hyper-V/WSL2 can conflict - try disabling Hyper-V or use the Windows Hypervisor Platform option in VirtualBox.
- *Port 8080 already in use on host*: change the host port in the forwarding rule (e.g. 8081) and browse to that.
- *`permission denied` running docker*: you skipped the `usermod` step - log out and in again.
