# VibeSyn Docker Deployment

This guide explains how to run the prebuilt VibeSyn website on a Linux server using Docker.

## Requirements

- A Linux server with Docker Engine installed and running.
- Access to Docker commands, either as a user with Docker permissions or with `sudo`.
- An `x86_64` server. The supplied image targets `linux/amd64`.
- An SSH connection to the server and a browser on your computer.

## 1. Download the image

Download the image from Google Drive and save it as `vibesyn.tar.gz`:

**Download link:** [GoogleDrive](https://drive.google.com/file/d/156O94L2LchiBadAfv9ga89MEU5oozGOw/view?usp=sharing)

Transfer the downloaded file to the server, for example:

```bash
scp vibesyn.tar.gz USER@SERVER:~/
```

Replace `USER@SERVER` with your SSH username and server address. The remaining commands run on the server after you connect with SSH. If your account requires `sudo` to access Docker, prefix each `docker` command below with `sudo`.

## 2. Load and start the image

Run these commands in the directory containing the image archive:

```bash
docker load -i vibesyn.tar.gz
```

Then start the container:

```bash
docker run -d \
  --name vibesyn \
  --restart unless-stopped \
  -p SERVER_LAN_IP:9000:9000 \
  vibesyn:latest
```

Replace `SERVER_LAN_IP` with the server's actual private IP address. Binding to that address makes the website accessible on that network without binding it to every interface. If port `9000` is already in use, change the host port (the first `9000`) to an available port, for example `SERVER_LAN_IP:9001:9000`. Ensure the server firewall permits access from the intended network.

Check that the container is running:

```bash
docker ps --filter name=vibesyn
curl -f http://SERVER_LAN_IP:9000/
```

The second command should return HTML. If you chose a different server port, substitute it for `9000`.

## 3. Open the website

From a computer on the same network, open `http://SERVER_LAN_IP:9000` in a browser, replacing `SERVER_LAN_IP` with the address used above. If you chose a different host port, use that port in the URL.

### Alternative: SSH tunnel

If you can reach the server by SSH but cannot connect to its website port directly, run this on your computer:

```bash
ssh -N -L 9000:SERVER_LAN_IP:9000 USER@SERVER
```

Replace `SERVER_LAN_IP` with the server address used in the Docker port mapping, and `USER@SERVER` with the SSH destination. Keep the terminal open and visit [http://localhost:9000](http://localhost:9000). Press `Ctrl+C` to close the tunnel. If you chose a different server port, change the last `9000`; if your computer's port `9000` is in use, change the first `9000` and use that port in the browser.

## Manage the container

```bash
# Stop the website
docker stop vibesyn

# Start it again
docker start vibesyn
```

## What is included

The image runs the website and its API and includes the task history and agent configuration present when it was built. It does not start the Python worker or supply model services, databases, or laboratory devices, so features that depend on those services may not work.
